# -*- coding: utf-8 -*-
"""产品清单：列表/详情/照片/导入/字段/跳过

由 server.py 按业务域切出，逻辑未改。
"""
import json
import os
import shutil
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

# deps 放最前：它负责 sys.path 引导
from tools.productlib.deps import (  # noqa: F401
    DATA_DIR, ROOT, THUMB_DIR, UPLOAD_DIR, WEB_DIR,
    _GOVERN, _LOCK, _photo_out, _run_govern, con,
)
from tools.productlib import pipeline, schema, store, vision

router = APIRouter()

# ═══════════════════════════════════════════════════════════════════
# 第 1 条：产品清单
# ═══════════════════════════════════════════════════════════════════

def _enrich_product_assets(con, rows):
    """资产化：给每个产品加 来源柜 / 被引用柜号 / 有标准图（批量查，杜绝 N+1）。

    - source_container_no：产品第一次被哪个柜的清单带进来
      （products.source_batch → batches.container_id → containers.container_no）
    - used_by：引用了该编码的柜号列表（checklist_rows.code_norm 去重）
    - has_std：标准图库里是否有该编码的图
    直接写进 rows（rows 已是 dict 列表）。
    """
    codes = [r.get('code_norm') for r in rows if r.get('code_norm')]
    if not codes:
        return
    qs = ','.join('?' * len(codes))
    std = {x[0] for x in con.execute(
        'SELECT DISTINCT code_norm FROM standard_images WHERE code_norm IN (%s)' % qs, codes)}
    used = {}
    for cn, cno in con.execute(
        'SELECT DISTINCT cr.code_norm, ct.container_no FROM checklist_rows cr'
        ' JOIN batches b ON b.id=cr.batch_id'
        ' JOIN containers ct ON ct.id=b.container_id'
        ' WHERE cr.code_norm IN (%s)' % qs, codes):
        used.setdefault(cn, []).append(cno)
    src = {}
    for cn, sb in con.execute(
        'SELECT code_norm, source_batch FROM products WHERE code_norm IN (%s)' % qs, codes):
        if sb and cn not in src:
            row = con.execute(
                'SELECT ct.container_no FROM batches b'
                ' JOIN containers ct ON ct.id=b.container_id WHERE b.id=?', (sb,)).fetchone()
            if row:
                src[cn] = row[0]
    for r in rows:
        cn = r.get('code_norm')
        r['source_container_no'] = src.get(cn)
        r['used_by'] = used.get(cn, [])
        r['has_std'] = cn in std


@router.get('/api/products')
def api_products(q: str = '', has: str = '', sort: str = 'code',
                 limit: int = 200, offset: int = 0, container: str = '',
                 cand: str = ''):
    """[has]: '' 全部 / 'yes' 有照片 / 'no' 无照片 / 'nostd' 未做标准图
    [cand]: '' 全部 / 'any' 有待确认照片 / 'code' 有读码候选 / 'group' 有同组候选
            —— 与列表角标同一份 store.cand_counts()，不会出现筛出来点开是空的
    [sort]: 'code' 按编码（默认）/ 'gap' 缺口优先 / 'cand' 待确认多的排前
    [container]: 按柜号筛选（通过 product_batch 或 links→photos→batches 关联）"""
    c = con()
    try:
        only = None
        only_std = None
        if has == 'yes':
            only = True
        elif has == 'no':
            only = False
        elif has == 'nostd':
            only_std = True
        elif has == 'cand':
            # 「有待确认」也可以走 has —— 前端下拉两种写法都收
            pass
        cont = (container or '').strip() or None
        oc = (cand or '').strip()
        if oc not in ('', 'any', 'code', 'group'):
            oc = ''
        if has == 'cand' and not oc:
            oc = 'any'
        st = sort if sort in ('code', 'gap', 'cand') else 'code'
        rows = store.list_products(c, keyword=q or None,
                                   only_with_photos=only,
                                   only_without_standard=only_std,
                                   sort=st,
                                   limit=limit, offset=offset,
                                   container_no=cont, only_cand=oc or None)
        total = store.count_products(c, keyword=q or None,
                                     only_with_photos=only,
                                     only_without_standard=only_std,
                                     container_no=cont,
                                     only_cand=oc or None)
        rows = [dict(r) for r in rows]
        _enrich_product_assets(c, rows)
        return {'items': rows, 'total': total}
    finally:
        c.close()


@router.get('/api/products/suggest')
def api_product_suggest(q: str = '', limit: int = 8):
    """编码联想（2026-10-19 老板需求：关联产品输入编码时要能联想）。

    抽屉里手输编码关联是高频操作，编码 14~16 位手打极易错 —— 输入
    后几位就能带出完整编码 + 品名，点选即填。轻量专用端点，不复用
    /api/products（那个带缩略图资产 enrich，200 条一次太重）。

    匹配口径与编码检索（v0.24.0）一致的方向：**包含式** LIKE（现场记
    后几位/中间几位，包含最实用），归一走 BL.normalize（全角转半角、
    去分隔符），排序按 code_norm 长度（短编码=常用排前）再按编码序。
    ⚠️ 字面量路由，必须排在 /api/products/{code} 之前（路由顺序坑）。
    """
    k = (q or '').strip()
    if not k:
        return {'items': []}
    c = con()
    try:
        kn = store.BL.normalize(k)   # 归一化复用 store 已导入的 build_library
        like = '%' + kn + '%'
        rows = c.execute(
            'SELECT code_norm, code, name FROM products '
            'WHERE code_norm LIKE ? OR name LIKE ? '
            'ORDER BY LENGTH(code_norm), code_norm LIMIT ?',
            (like, '%' + k + '%', max(1, min(20, limit)))).fetchall()
        return {'items': [dict(r) for r in rows]}
    finally:
        c.close()


@router.get('/api/products/containers')
def api_product_containers():
    """产品库「柜号」下拉的选项：**以产品清单里的柜号为准**（老板 10-05）。

    不用 `/api/batches` 的照片批次柜号 —— 那份既混进与产品无关的柜号，
    又漏掉只登记在清单里、还没拍照的柜号。详见 store.product_containers。
    """
    c = con()
    try:
        return {'items': store.product_containers(c)}
    finally:
        c.close()


@router.get('/api/products/template')
def api_product_template():
    """下载货品清单导入模板（xlsx），含表头说明 + 示例数据。"""
    import io
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        raise HTTPException(500, 'openpyxl 未安装，无法生成模板')
    wb = Workbook()
    # ── Sheet1: 模板 ──
    ws = wb.active
    ws.title = '货品清单'
    headers = ['编码（必填）', '品名', '规格', '数量', '箱号']
    examples = [
        ['105025023334C', '不锈钢法兰', 'DN50 PN16', 10, 'C-01'],
        ['213010003118', '橡胶垫片', 'φ80×3mm', 50, 'C-01'],
        ['101065103007B', '六角螺栓', 'M12×40 8.8级', 200, 'C-02'],
    ]
    # 表头样式
    hdr_font = Font(bold=True, color='FFFFFF', size=11)
    hdr_fill = PatternFill('solid', fgColor='4472C4')
    hdr_align = Alignment(horizontal='center', vertical='center')
    thin = Side(style='thin', color='B0B0B0')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = hdr_align
        cell.border = border
    # 示例数据
    for ri, row in enumerate(examples, 2):
        for ci, v in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci, value=v)
            cell.border = border
            cell.alignment = Alignment(vertical='center')
    # 列宽
    widths = [20, 24, 22, 10, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w
    # 编码列设为文本格式，避免长数字变科学计数
    for row in ws.iter_rows(min_row=2, max_row=1000, min_col=1, max_col=1):
        for cell in row:
            cell.number_format = '@'

    # ── Sheet2: 填写说明 ──
    ws2 = wb.create_sheet('填写说明')
    notes = [
        ['货品清单导入模板 — 填写说明', ''],
        ['', ''],
        ['列名', '说明'],
        ['编码（必填）', '产品编码/料号/型号，支持中英文表头自动识别（Model No、Part Number、物料编码、料号等）'],
        ['品名', '产品名称/描述（Description、Name、品名等均可识别）'],
        ['规格', '规格型号（Spec、Specification、规格等均可识别）'],
        ['数量', '数量（Qty、Quantity、数量等均可识别），选填'],
        ['箱号', '箱号/托盘号（Carton、Container、箱号、Pallet等均可识别），选填，用于复盘整箱是否拍到'],
        ['', ''],
        ['注意事项', ''],
        ['1', '编码列必须有，其他列可选'],
        ['2', '表头不要求在第1行，系统会在前15行自动定位表头'],
        ['3', '编码列请设为"文本"格式，避免长数字编码被 Excel 转成科学计数法或丢精度'],
        ['4', '支持 .xls 和 .xlsx 格式'],
        ['5', '同一编码在多行出现会自动合并，箱号会汇总'],
        ['6', '导入时请填写柜号，与照片批次的柜号统一，便于检索时按柜号加载清单'],
    ]
    title_font = Font(bold=True, size=14, color='1F4E79')
    note_hdr_font = Font(bold=True, size=11)
    for ri, (a, b) in enumerate(notes, 1):
        ca = ws2.cell(row=ri, column=1, value=a)
        cb = ws2.cell(row=ri, column=2, value=b)
        if ri == 1:
            ca.font = title_font
        elif a in ('列名', '注意事项'):
            ca.font = note_hdr_font
            cb.font = note_hdr_font
    ws2.column_dimensions['A'].width = 18
    ws2.column_dimensions['B'].width = 80

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from urllib.parse import quote
    fname = quote('货品清单导入模板.xlsx')
    return Response(content=buf.getvalue(),
                    media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': "attachment; filename*=UTF-8''%s" % fname})

@router.get('/api/products/{code}')
def api_product(code: str):
    c = con()
    try:
        r = c.execute('SELECT * FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not r:
            raise HTTPException(404, '产品不存在')
        out = dict(r)
        # 来源信息：清单导入 / 照片新发现确认 + 关联柜号列表
        out['origins'] = store.product_origins(c, r['code_norm'])
        return out
    finally:
        c.close()


@router.get('/api/products/{code}/photos')
def api_product_photos(code: str):
    """第 5 条：一个产品的所有预检采集图片。"""
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(404, '产品不存在')
        rows, batches, missing = store.product_photos_grouped(c, p['code_norm'])
        # G1：该产品做过标准图的「源照片」id 集 —— 前端照片卡据此打「标」角标。
        # 只算裁剪来源：上传的标准图 src_photo_id 是哨兵值（_UPLOADED_，表约束
        # NOT NULL 塞的占位），不是真实照片 id，混进来会让「N 张标准图」虚高。
        std_ids = [r['src_photo_id'] for r in c.execute(
            "SELECT DISTINCT src_photo_id FROM standard_images"
            " WHERE code_norm=? AND IFNULL(origin,'crop')='crop'",
            (p['code_norm'],)).fetchall()]
        # 标准图总数（裁剪 + 上传）—— 标题区「N 张标准图」用它：一个源照片可以
        # 存多个版本，上传的也不挂照片，std_ids 的个数不是标准图张数。
        std_count = c.execute(
            'SELECT COUNT(*) FROM standard_images WHERE code_norm=?',
            (p['code_norm'],)).fetchone()[0]
        return {
            'code': p['code_norm'],
            'items': [_photo_out(c, r) for r in rows],
            'standard_photo_ids': std_ids,
            'standard_count': std_count,
            # 批次视角：右栏按批次分组 + 列出「哪些批次没图」
            'batches': batches,
            'missing_batches': missing,
        }
    finally:
        c.close()


@router.get('/api/products/{code}/candidates')
def api_product_candidates(code: str):
    """该产品编码的候选未关联照片。

    包含三类推荐：
    - items：读码匹配到的候选照片（「可能关联的图片」）
    - group_siblings：已关联照片的同组其他照片（标签特写+全景图连拍，
      强语义推荐，优先展示）。🔴 2026-10-11 已**收敛**：按 import_seq 取最近 3 张
      （原先整组给，微信来源实测一次 29 张）。
    - panoramas：**可能的全景图** —— 由已关联的标签近景推出来的邻近照片
      （产品本体照/包装照，照片上没编码所以系统认不出来，只能"建议 + 人工确认"）。
      只在该产品**缺**产品/包装类照片时给，顺序走 import_seq 而不是 taken_at
      （微信转来的图没有 EXIF，时间是接收时间）。
    - rejected：被人工标记「无关联」的（默认不返回，前端按需单查）
    """
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(404, '产品不存在')
        cn = p['code_norm']
        items = store.product_candidates(c, cn)
        siblings = store.product_group_siblings(c, cn)
        panos = store.product_panorama_candidates(c, cn)
        return {'items': items, 'total': len(items),
                'group_siblings': siblings, 'sibling_total': len(siblings),
                'panoramas': panos, 'panorama_total': len(panos)}
    finally:
        c.close()


@router.post('/api/products/{code}/candidates/reject')
def api_reject_candidate(code: str, payload: dict):
    """标记候选照片「与该产品无关联」（10-05 老板口径）。

    标完这张照片不再出现在该产品的「可能关联的图片 / 同组待确认」里，
    列表的「待确认」角标同步下降。**只影响这一个产品** —— 同一张照片
    若是别的产品的候选，仍然照常出现（老板否的是「它不是 A 的」，
    不是「它不属于任何产品」）。

    人工关联时会自动清掉同对的否决记录，所以反悔了直接关联即可。
    """
    pids = [p for p in (payload.get('photo_ids') or []) if p]
    if not pids:
        raise HTTPException(400, '没指定要标记哪张照片')
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(404, '产品不存在')
        cn = p['code_norm']
        reason = (payload.get('reason') or '').strip() or None
        by = (payload.get('by') or 'user').strip() or 'user'
        n = 0
        for pid in pids:
            if store.reject_candidate(c, cn, pid, reason=reason, by=by):
                n += 1
        # 计数与详情同源：标记后角标必须立刻降，不能等 60s 缓存过期
        store.invalidate_cand_cache()
        return {'ok': True, 'code_norm': cn, 'marked': n,
                'skipped': len(pids) - n}
    finally:
        c.close()


@router.post('/api/products/{code}/candidates/unreject')
def api_unreject_candidate(code: str, payload: dict):
    """撤销「无关联」标记 —— 这张照片回到候选列表。"""
    pids = [p for p in (payload.get('photo_ids') or []) if p]
    if not pids:
        raise HTTPException(400, '没指定要撤销哪张照片')
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(404, '产品不存在')
        cn = p['code_norm']
        n = 0
        for pid in pids:
            n += store.unreject_candidate(c, cn, pid)
        store.invalidate_cand_cache()
        return {'ok': True, 'code_norm': cn, 'unmarked': n}
    finally:
        c.close()


@router.get('/api/products/{code}/candidates/rejected')
def api_list_rejected(code: str):
    """该产品被标记「无关联」的清单 —— 给老板一个反悔的入口。"""
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(404, '产品不存在')
        items = store.cand_rejects(c, p['code_norm'])
        for it in items:
            it['thumb'] = '/thumb/%s' % it['photo_id']
            it['full'] = '/img/%s' % it['photo_id']
        return {'items': items, 'total': len(items)}
    finally:
        c.close()



@router.post('/api/products/import')
def api_import_checklist(file: UploadFile = File(...), replace: bool = Form(False),
                         container_id: str = Form(''), container_no: str = Form('')):
    """上传 xls/xlsx 清单。字段规范校验在 store.validate_product 里。

    ⚠️ 2026-10-05 v3：container_id 必填（无柜不导）。container_no 只作兼容
    兜底（旧链接/脚本），推荐显式传 id —— 「先建柜」是流程第一步。
    """
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ('.xls', '.xlsx'):
        raise HTTPException(400, '只支持 .xls / .xlsx（当前：%s）' % (ext or '无扩展名'))
    if not (container_id or '').strip() and not (container_no or '').strip():
        raise HTTPException(400, '请先选择柜（先到「柜」页新建或选一个柜）')
    dst_dir = os.path.join(UPLOAD_DIR, 'checklist')
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, '%s_%s' % (uuid.uuid4().hex[:8], file.filename))
    with open(dst, 'wb') as f:
        shutil.copyfileobj(file.file, f)

    c = con()
    try:
        r = store.import_checklist_file(
            c, dst, batch_name=file.filename, replace=replace,
            container_id=(container_id or '').strip() or None,
            container_no=(container_no or '').strip() or None)
        # 补关联：照片先于清单导入时，自动关联已经全部落空
        # （索引建自 products 表，导入顺序反了就一条也匹配不上，
        #   且照片 govern_state 已是 done，重跑治理扫不到它们）。
        # 这里用新清单把已落库的 OCR token / 多模态码重匹配一遍 ——
        # 不重跑识别、不花 API 钱，照片/清单任一顺序导入都能自动关联。
        try:
            r['relink'] = pipeline.relink_due_to_checklist(c)
        except Exception as e:  # noqa: BLE001
            # 补关联失败**不能**让清单导入失败 —— 清单已经进库了，
            # 关联可以之后单独重试。错误原样带回，前端要能看见。
            r['relink_error'] = str(e)[:200]
        return r
    except store.ContainerError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '清单解析失败：%s' % e)
    finally:
        c.close()


@router.post('/api/products/relink')
def api_relink(limit: int = 0):
    """手动补关联：把已治理但没关联上的照片，用当前产品库重匹配一遍。

    什么时候需要手动点：
      · 照片先导、清单后导（自动触发过，这里可再补一次兜底）；
      · 手工补了/改了产品编码，希望把已有照片挂上去；
      · 调了归一化或纠偏规则，想重算一遍（只补缺失，不动已有的）。
    只补**没有自动关联**的照片，人工关联永不动。
    """
    c = con()
    try:
        return pipeline.relink_due_to_checklist(c, limit=limit or None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '补关联失败：%s' % e)
    finally:
        c.close()


@router.get('/api/checklist-batches')
def api_checklist_batches():
    """所有清单导入批次（含柜号、产品数、时间），用于检索页按柜号加载清单。"""
    c = con()
    try:
        return {'items': store.list_checklist_batches(c)}
    finally:
        c.close()


@router.get('/api/batches/{bid}/products')
def api_batch_products(bid: str):
    """某个清单批次下的所有产品编码，用于检索页一键加载货品清单。"""
    c = con()
    try:
        return {'items': store.products_by_batch(c, bid)}
    finally:
        c.close()


@router.delete('/api/products/{code}')
def api_delete_product(code: str):
    """删除一个产品，级联清理关联、标准图、批次关联。不删除原照片。"""
    import build_library as BL
    cn = BL.normalize(code)
    c = con()
    try:
        n = store.delete_product(c, cn)
        if n == 0:
            raise HTTPException(404, '产品不存在')
        return {'ok': True, 'deleted': cn}
    finally:
        c.close()


@router.post('/api/products')
def api_add_product(payload: dict):
    """手工补录单个产品（清单里没有、但照片上出现了的编码）。"""
    c = con()
    try:
        added, updated, errors = store.upsert_products(c, [payload], replace=False)
        if errors:
            raise HTTPException(400, errors[0]['errors'])
        return {'added': added, 'updated': updated}
    finally:
        c.close()


@router.patch('/api/products/{code}')
def api_update_product(code: str, payload: dict):
    """内联编辑产品字段（品名 / 规格 / 材质 …）。

    编码不可改 —— 改了等于换一件货。只接受 PRODUCT_FIELDS 里的业务字段。
    """
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(404, '产品不存在')
        n = store.update_product_fields(c, p['code_norm'], payload)
        if not n:
            raise HTTPException(400, '没有可更新的字段（编码不可改）')
        r = c.execute('SELECT * FROM products WHERE code_norm=?',
                      (p['code_norm'],)).fetchone()
        return {'ok': True, 'product': dict(r)}
    finally:
        c.close()


@router.post('/api/photos/skip')
def api_photo_skip(payload: dict):
    """人工标注时的「跳过」—— 持久记忆，不再回待认领队列。

    body: {photo_id, skip(默认 true), by}
    skip=false 即撤销跳过（照片回到待认领队列）。
    """
    pid = (payload.get('photo_id') or '').strip()
    if not pid:
        raise HTTPException(400, '缺少 photo_id')
    skip = bool(payload.get('skip', True))
    c = con()
    try:
        if not c.execute('SELECT 1 FROM photos WHERE id=?', (pid,)).fetchone():
            raise HTTPException(404, '照片不存在')
        store.set_photo_skip(c, pid, skip=skip,
                             by=(payload.get('by') or 'user'))
        return {'ok': True, 'photo_id': pid, 'skip': skip}
    finally:
        c.close()


@router.get('/api/photos/skipped')
def api_photos_skipped(limit: int = 60, offset: int = 0):
    """已跳过的照片（撤销入口的数据源）。"""
    c = con()
    try:
        rows = store.skipped_photos(c, limit=limit, offset=offset)
        total = c.execute(
            'SELECT COUNT(*) FROM photos WHERE COALESCE(manual_skip,0)=1').fetchone()[0]
        return {'total': total, 'items': [_photo_out(c, r) for r in rows]}
    finally:
        c.close()


@router.get('/api/fields')
def api_fields():
    """产品数据规范 —— 界面上的表头与提示直接取自这里，不二次抄写。"""
    return {
        'fields': [{'name': n, 'label': l, 'required': r, 'desc': d}
                   for n, l, r, d in schema.PRODUCT_FIELDS],
        'kinds': schema.PHOTO_KINDS,
        'sources': schema.LINK_SOURCES,
    }
