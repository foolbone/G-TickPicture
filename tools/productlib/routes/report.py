# -*- coding: utf-8 -*-
"""报告素材：编码检索/素材包导出

由 server.py 按业务域切出，逻辑未改。
"""
import json
import os
import shutil
import time
import uuid
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# deps 放最前：它负责 sys.path 引导
from tools.productlib.deps import (  # noqa: F401
    DATA_DIR, ROOT, THUMB_DIR, UPLOAD_DIR, WEB_DIR,
    _GOVERN, _LOCK, _photo_out, _run_govern, con,
)
from tools.productlib import pipeline, report_gen, schema, store, vision

router = APIRouter()

# ═══════════════════════════════════════════════════════════════════
# 第 9 条：报告素材（清单编码 → 批次/标准库快速检索 → 素材包落盘）
# ═══════════════════════════════════════════════════════════════════

def _codes_from_payload(payload):
    """body 里的编码列表：codes 直接给，或 text 粘贴文本按分隔符切。"""
    codes = payload.get('codes') or []
    if isinstance(codes, str):
        codes = [codes]
    text = payload.get('text') or ''
    if text:
        import re as _re
        codes += [s for s in _re.split(r'[\s,，、;；\t]+', text) if s]
    # 保序去重
    seen, out = set(), []
    for c in codes:
        c = str(c or '').strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


@router.post('/api/report/lookup')
def api_report_lookup(payload: dict):
    """报告素材检索。body: {codes:[...] | text:'粘贴文本', batch_ids:[...],
    std_only:bool, std_prefer:bool, strategy:str}

    [strategy] 自动选图策略（默认 balanced）。决定 recommended 给哪一张，
    同时影响「全部采用建议图」采用到哪张。
    """
    codes = _codes_from_payload(payload)
    if not codes:
        raise HTTPException(400, '没有可检索的编码')
    strategy = (payload.get('strategy') or 'balanced').strip()
    if strategy not in store.PICK_STRATEGIES:
        # 🔴 明确报错而不是静默回退成 balanced：静默回退会让「我以为选了
        #    优先标准图、其实还是均衡」变成一个查不出来的错觉。
        raise HTTPException(400, '未知选图策略：%s（可选：%s）'
                            % (strategy, ' / '.join(store.PICK_STRATEGIES)))
    c = con()
    try:
        items = store.report_lookup(c, codes,
                                    batch_ids=payload.get('batch_ids') or [],
                                    std_only=bool(payload.get('std_only', False)),
                                    std_prefer=bool(payload.get('std_prefer', True)),
                                    container_id=(payload.get('container_id') or '').strip() or None,
                                    strategy=strategy)
        return {'items': items,
                'matched': sum(1 for r in items if r['found']),
                'missing': sum(1 for r in items if not r['found']),
                # 策略清单由后端下发 —— 前端别自己再写一份，写两份必然漂移
                'strategy': strategy,
                'strategy_label': store.PICK_STRATEGY_LABELS.get(strategy, strategy),
                'strategies': [{'key': k, 'label': store.PICK_STRATEGY_LABELS[k]}
                               for k in store.PICK_STRATEGIES]}
    finally:
        c.close()


@router.post('/api/report/export')
def api_report_export(payload: dict):
    """素材包落盘。body: {dir, codes|text, batch_ids, all_photos}"""
    out_dir = (payload.get('dir') or '').strip()
    if not out_dir:
        raise HTTPException(400, '请填写导出目录')
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        raise HTTPException(400, '该路径不是目录：%s' % out_dir)
    codes = _codes_from_payload(payload)
    if not codes:
        raise HTTPException(400, '没有可导出的编码')
    c = con()
    try:
        # G2 长边压缩（默认 1600，0=原图）；G4 人工指定采用照 {编码: photo_id}
        try:
            long_edge = int(payload.get('long_edge') or 1600)
        except (TypeError, ValueError):
            long_edge = 1600
        picks = payload.get('picks') or {}
        if not isinstance(picks, dict):
            picks = {}
        return store.report_export(c, out_dir, codes,
                                   batch_ids=payload.get('batch_ids') or [],
                                   all_photos=bool(payload.get('all_photos', False)),
                                   long_edge=long_edge, picks=picks)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '导出失败：%s' % e)
    finally:
        c.close()


@router.post('/api/report/codes-from-file')
async def api_report_codes_from_file(file: UploadFile = File(...)):
    """从清单文件提取编码列表（复用 parse_checklist：表头定位/箱号填充/数字去尾零）。"""
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ('.xls', '.xlsx'):
        raise HTTPException(400, '只支持 .xls / .xlsx（当前：%s）' % (ext or '无扩展名'))
    dst_dir = os.path.join(UPLOAD_DIR, 'report')
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, '%s_%s' % (uuid.uuid4().hex[:8], file.filename))
    with open(dst, 'wb') as f:
        shutil.copyfileobj(file.file, f)
    try:
        import build_library as BL
        items, _meta = BL.parse_checklist(dst)
        merged = BL.merge_items(items)
        codes, seen = [], set()
        for m in merged:
            code = str(m.get('code') or '').strip()
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
        return {'codes': codes, 'count': len(codes), 'file': file.filename}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '清单解析失败：%s' % e)
    finally:
        try:
            os.remove(dst)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════
# 装柜报告 docx（2026-10-05 v3）
# ═══════════════════════════════════════════════════════════════════

REPORT_DIR = os.path.join(DATA_DIR, 'reports')


@router.get('/api/report/loading-preview')
def api_loading_preview(container_id: str, reverse: int = 1):
    """出报告前的告知（不拦截）。数字与生成器同源 —— 同一份 loading_report_data。"""
    if not (container_id or '').strip():
        raise HTTPException(400, '请先选择柜')
    c = con()
    try:
        d = store.loading_report_data(c, container_id.strip(),
                                      reverse_checks=bool(int(reverse or 1)))
        s = d['summary']
        return {'meta': d['meta'], 'summary': s,
                'rows_preview': d['rows'][:8],
                'truck_preview': [{'photo_id': t['photo_id'], 'tag': t['tag']}
                                  for t in d['trucks'][:6]]}
    except store.ContainerError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post('/api/report/loading-docx')
def api_loading_docx(payload: dict):
    """按柜生成装柜报告 docx，落盘 data/reports/ 并返回路径与体积。

    body: {container_id, template?, reverse?, long_edge?}

    ⚠️ 端点是同步 `def`（不是 async def）—— FastAPI 会把它丢到线程池执行，
    生成 1000 行 + 400 图要几十秒，放事件循环里会把整个页面卡死。
    """
    cid = (payload.get('container_id') or '').strip()
    if not cid:
        raise HTTPException(400, '请先选择柜（先到「柜」页新建或选一个柜）')
    try:
        long_edge = int(payload.get('long_edge') or report_gen.PHOTO_LONG_EDGE)
    except (TypeError, ValueError):
        long_edge = report_gen.PHOTO_LONG_EDGE
    c = con()
    try:
        d = store.loading_report_data(
            c, cid, reverse_checks=bool(payload.get('reverse', True)),
            picks=payload.get('picks') or None)
        # 照片相对路径的基准根（= **这个库**文件所在目录）。必须在 close 之前
        # 取，且不能用 paths.data_dir()：多库/便携化场景下库不一定在默认 data 根。
        photo_root = store._data_root(c)
    except store.ContainerError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()

    meta = d['meta']
    if meta.get('is_uncategorized'):
        raise HTTPException(400, '这是「未分柜」，请先补柜号并把批次改挂到正式柜')
    if not d['rows']:
        raise HTTPException(400, '这个柜还没有导入产品清单，没法出 Packing list')

    os.makedirs(REPORT_DIR, exist_ok=True)
    tpl = report_gen.load_template((payload.get('template') or '').strip(), DATA_DIR)
    date = meta.get('inspection_date') or ''
    safe_cno = _safe_fn(meta['container_no'])
    fname = 'LOADING REPORT-CNTR#%s-%s.docx' % (safe_cno, date.replace(' ', '_')
                                              .replace(',', ''))
    out = os.path.join(REPORT_DIR, fname)
    try:
        r = report_gen.build_loading_report(d, out, template=tpl, long_edge=long_edge,
                                            photo_root=photo_root)
    except PermissionError:
        # 到这里还没成，说明连「加时分秒另存」都失败（目录权限/磁盘满）
        raise HTTPException(500, '报告生成失败：无法写入 %s —— 关闭占用它的程序，'
                                 '或检查磁盘/目录权限' % fname)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '报告生成失败：%s' % str(e)[:300])
    # ⚠️ 下载链接要用**实际落盘**的文件名：同名文件被 Word 占住时生成器会
    #    自动加时分秒另存（见 report_gen._save_report），链接必须跟着走。
    #    另外文件名里的 `#`（CNTR#柜号）不做 URL 编码的话，浏览器把 # 之后
    #    当页面片段，服务器收到的 path 被截成 `LOADING REPORT-CNTR`，
    #    下载直接 400「只允许下载 .docx」。quote 一次性处理 #、空格、中文。
    real_name = os.path.basename(r.get('path') or fname)
    r['download'] = '/api/report/loading-file?path=' + quote(real_name)
    r['container_no'] = meta['container_no']
    r['summary'] = d['summary']
    if r.get('renamed'):
        r['note'] = ('同名文件正被占用（多半在 Word 里开着），已另存为 %s'
                     % real_name)
    return r


def _report_files():
    """已生成报告清单（新→旧）。报告中心④「已生成报告」的数据源。"""
    out = []
    # 清残留：生成中途挂掉会留下 `*.docx.tmp`（正常路径不会留下）
    try:
        import time as _t
        for fn in os.listdir(REPORT_DIR):
            if fn.endswith('.docx.tmp') and _t.time() - os.path.getmtime(
                    os.path.join(REPORT_DIR, fn)) > 3600:
                os.remove(os.path.join(REPORT_DIR, fn))
    except OSError:
        pass
    if os.path.isdir(REPORT_DIR):
        for fn in os.listdir(REPORT_DIR):
            if not fn.lower().endswith('.docx'):
                continue
            full = os.path.join(REPORT_DIR, fn)
            try:
                st = os.stat(full)
            except OSError:
                continue
            out.append({
                'name': fn, 'bytes': st.st_size,
                'mtime': datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds'),
                'download': '/api/report/loading-file?path=' + quote(fn),
            })
    out.sort(key=lambda x: x['mtime'], reverse=True)
    return out


@router.get('/api/report/loading-list')
def api_loading_list():
    """已生成报告列表 + 占用空间。老板常要「上周那版再发一次」—— 没有列表
    就只能重跑一遍（1000 行 250 图 = 20 秒 + 一份重复文件）。"""
    items = _report_files()
    import re as _re
    for it in items:
        m = _re.search(r'CNTR#([^-]+)-', it.get('name', ''))
        it['container_no'] = m.group(1) if m else None
    return {'items': items, 'total_bytes': sum(x['bytes'] for x in items),
            'dir': REPORT_DIR}


@router.delete('/api/report/loading-file')
def api_loading_delete(path: str):
    """删除一份已生成报告（basename 白名单，禁目录穿越）。"""
    name = os.path.basename(path or '')
    if not name or not name.lower().endswith('.docx'):
        raise HTTPException(400, '只允许删除 .docx')
    full = os.path.join(REPORT_DIR, name)
    if not os.path.exists(full):
        raise HTTPException(404, '文件不存在（可能已被删除）')
    try:
        os.remove(full)
    except OSError as e:
        raise HTTPException(500, '删除失败：%s' % e)
    return {'ok': True, 'deleted': name}


@router.get('/api/report/loading-file')
def api_loading_file(path: str):
    """下载生成的报告。path 只接受 basename —— 绝不允许传目录穿越。"""
    name = os.path.basename(path or '')
    if not name or not name.lower().endswith('.docx'):
        raise HTTPException(400, '只允许下载 .docx')
    full = os.path.join(REPORT_DIR, name)
    if not os.path.exists(full):
        raise HTTPException(404, '文件不存在（可能已被清理，重新生成一次）')
    return FileResponse(full, filename=name,
                        media_type='application/vnd.openxmlformats-officedocument'
                                   '.wordprocessingml.document')


@router.get('/api/report/templates')
def api_report_templates():
    """可用抬头模板（data/report_templates/*.json + 内置默认）。"""
    d = os.path.join(DATA_DIR, 'report_templates')
    items = [{'name': 'default', 'label': 'SZAE（内置默认）'}]
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.endswith('.json'):
                items.append({'name': fn[:-5], 'label': fn[:-5]})
    return {'items': items}


def _safe_fn(s):
    import re as _re
    out = _re.sub(r'[\\/:*?"<>|]', '_', (s or '').strip())
    return out or 'UNKNOWN'
