# -*- coding: utf-8 -*-
"""打包版实测（pl-v0.10.0 发版铁律：源码全绿 != 打包版能跑）。

隔离 PL_HOME + 端口 8795 起 exe，验证：
  · /api/ping version=0.18.1 mode=frozen
  · 本轮新端点 /api/govern/stop（0.12.0 时不存在，404 即旧代码）
  · 版本 0.18.1：报告照片路径便携化修复
  · 版本 0.18.0：柜作业时长（/api/containers 的 work + 详情的 work_segments）
  · 版本 0.17.0：分类多选 IN / sort 排序 / 抽屉合并候选 / 联想 / regovern mode
  · 本轮新端点 POST /api/photos/ignore（0.13.0 时不存在，404 即旧代码）
  · 导 xlsx 清单 + 出报告 → docx pgSz=11909x16834（A4）
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

EXE = r'D:\G-TickPicture\dist\20261020_193953\集刻产品库\集刻产品库.exe'
PORT = 8795
DBHOME = os.environ.get('PL_PKG_DB') or os.path.join(tempfile.gettempdir(), 'pl_pkgA_db')
REPO = r'D:\G-TickPicture'
XLSX = os.path.join(REPO, '9.13 5x40HQ', 'MIEU2012616.xlsx')

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


shutil.rmtree(DBHOME, ignore_errors=True)
os.makedirs(DBHOME, exist_ok=True)

# 🔴 偶发 500 排查：exe 的 stderr 落文件（Internal Server Error 没有堆栈就是抓瞎）
_errlog = open(os.path.join(tempfile.gettempdir(), 'pl_pkgA_exe_err.log'), 'wb')
srv = subprocess.Popen([EXE, '--port', str(PORT)],
                       env={**os.environ, 'PL_HOME': DBHOME},
                       stdout=_errlog, stderr=subprocess.STDOUT)

BASE = 'http://127.0.0.1:%d' % PORT


def http_json(path, retries=60, timeout=8):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
                return json.loads(r.read().decode('utf8'))
        except Exception:
            time.sleep(0.5)
    return None


def post_json(path, obj, timeout=600):
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(obj).encode('utf8'),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf8', 'replace')
        try:
            return e.code, json.loads(body or '{}')
        except Exception:
            return e.code, {'raw': body[:300]}


def post_file(path, fields, files, timeout=900):
    b = '----plpkgA' + str(int(time.time()))
    buf = b''
    for k, v in fields.items():
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                % (b, k, v)).encode('utf8')
    for k, fp, fn in files:
        with open(fp, 'rb') as f:
            data = f.read()
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n' % (b, k, fn)).encode('utf8')
        buf += data + b'\r\n'
    buf += ('--%s--\r\n' % b).encode('utf8')
    req = urllib.request.Request(BASE + path, data=buf,
                                 headers={'Content-Type':
                                          'multipart/form-data; boundary=%s' % b})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf8', 'replace')
        try:
            return e.code, json.loads(body or '{}')
        except Exception:
            return e.code, {'raw': body[:300]}


try:
    ping = http_json('/api/ping')
    chk('1 打包版起来了 /api/ping', ping is not None, ping)
    chk('2 version=0.18.1', (ping or {}).get('version') == '0.18.1',
        (ping or {}).get('version'))
    chk('3 mode=frozen（PyInstaller 模式）', (ping or {}).get('mode') == 'frozen',
        (ping or {}).get('mode'))

    code, c = post_json('/api/containers',
                        {'container_no': 'PKGA001', 'seal_no': 'S9',
                         'inspector': 'pkg'})
    cid = (c or {}).get('id')
    chk('4 建柜', bool(cid), cid)

    code, r = post_file('/api/products/import', {'container_id': cid},
                        [('file', XLSX, os.path.basename(XLSX))])
    chk('5 导入真实清单', code == 200 and (r or {}).get('snap_rows', 0) > 20,
        (r or {}).get('snap_rows'))

    # 上传 2 张监装照并打细分（其中 1 张已确认 → 待办只剩另 1 类）
    from PIL import Image
    tmpd = os.path.join(tempfile.gettempdir(), 'pl_pkgA_photos')
    os.makedirs(tmpd, exist_ok=True)
    files = []
    for i in range(2):
        p = os.path.join(tmpd, 'PK_%02d.jpg' % i)
        Image.new('RGB', (1200, 900), (60 * i, 90, 200)).save(p)
        files.append(('files', p, os.path.basename(p)))
    code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
    chk('6 上传 2 张照片', code == 200 and (r or {}).get('added', 0) == 2,
        '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:300]))
    ph = http_json('/api/photos?container_id=%s&limit=20' % cid) or {}
    items = ph.get('items') or []
    for it, tg in zip(items, ['empty_container', 'truck_head']):
        req = urllib.request.Request(
            BASE + '/api/photos/%s/usage' % it['id'],
            data=json.dumps({'usage': '监装', 'by': 'pkg'}).encode('utf8'),
            headers={'Content-Type': 'application/json'}, method='PATCH')
        try:
            urllib.request.urlopen(req, timeout=30).read()
        except urllib.error.HTTPError as e:
            chk('6b usage PATCH 失败详情', False,
                '%s %s' % (e.code, e.read().decode('utf8', 'replace')[:300]))
            raise
        post_json('/api/photos/supervision-tag',
                  {'photo_ids': [it['id']], 'tag': tg, 'by': 'pkg'}, timeout=30)

    # 0.18.0 新能力：柜作业时长（老包里 list_containers 不回 work、
    # container_detail 不回 work_segments —— 少字段即旧代码）
    cl = http_json('/api/containers') or {}
    mine = next((x for x in (cl.get('items') or [])
                 if x.get('id') == cid), {})
    wk = mine.get('work') or {}
    chk('0.18a 柜列表带作业时长汇总 work',
        bool(wk) and wk.get('segments', 0) >= 1 and 'active_sec' in wk, wk)
    det = http_json('/api/containers/%s' % cid) or {}
    segs = det.get('work_segments') or []
    chk('0.18b 柜详情带逐段明细 work_segments',
        bool(segs) and 'span_sec' in segs[0] and 'trusted' in segs[0],
        segs[:1])

    # 本轮新端点：facets（左侧树形筛选，2026-10-14），404 即旧代码
    f = http_json('/api/photos/facets?container_id=%s' % cid) or {}
    chk('7 新端点 photos/facets 在打包版里存在（非404）',
        'usage' in f and 'kind' in f, f)
    cg = http_json('/api/photos/carton-groups?container_id=%s' % cid) or {}
    chk('7c 新端点 photos/carton-groups（按箱号分组）',
        'total' in cg and 'items' in cg, cg)
    # 0.16.0 新端点：编码联想 + 合并候选（抽屉三连，2026-10-18/19）
    sg = http_json('/api/products/suggest?q=%s' % '1030') or {}
    chk('7e 新端点 products/suggest（编码联想）',
        isinstance(sg.get('items'), list), sg)
    if items:
        pn = http_json('/api/photos/%s/panoramas' % items[0]['id']) or {}
        chk('7f panoramas 返回合并结构（items+siblings）',
            'items' in pn and 'siblings' in pn,
            sorted(pn.keys()))
        code, rr = post_json('/api/photos/%s/regovern' % items[0]['id'],
                             {'mode': 'ocr'}, timeout=60)
        chk('7g regovern mode=ocr 在打包版可跑',
            code == 200 and (rr or {}).get('mode') == 'ocr',
            '%s %s' % (code, json.dumps(rr, ensure_ascii=False)[:150]))
        # 0.17.0 新能力：分类多选（逗号 IN）+ 排序参数（老代码没有会 400/忽略）
        # ⚠️ 隔离库只上传了 2 张未分类照片（kind=_unset），所以用 _unset
        #    做多选素材、并断言「不报错 + 多选 ⊇ 单选」，不写死条数 ——
        #    写死 5 条会因隔离库只有 2 张而假红（第一次跑就栽在这）。
        m1 = http_json('/api/photos?kind=_unset&limit=5') or {}
        m2 = http_json('/api/photos?kind=_unset,label&limit=5') or {}
        chk('7h 分类多选（逗号 IN）在打包版可跑且 ⊇ 单选',
            'items' in m1 and 'items' in m2
            and m2.get('total', 0) >= m1.get('total', 0),
            {'_unset': m1.get('total'), '_unset+label': m2.get('total')})
        s1 = http_json('/api/photos?sort=code&limit=5') or {}
        s2 = http_json('/api/photos?sort=state&limit=5') or {}
        chk('7i sort 排序参数（code/state）在打包版可跑',
            0 < len(s1.get('items', [])) <= 5 and 0 < len(s2.get('items', [])) <= 5,
            'code=%s state=%s' % (len(s1.get('items', [])), len(s2.get('items', []))))
    # 本轮新端点：photos/kind（③批量改判分类，0.11.0 时不存在，404 即旧代码）
    if items:
        code, kr = post_json('/api/photos/kind',
                             {'photo_ids': [items[0]['id']],
                              'kind': 'product', 'by': 'pkg'}, timeout=30)
        chk('7d 新端点 photos/kind（批量改判分类）',
            code == 200 and (kr or {}).get('updated') == 1
            and (kr or {}).get('kind') == 'product',
            '%s %s' % (code, json.dumps(kr, ensure_ascii=False)[:200]))
    # linkstate 收窄参数（树选监装后徽章跟着收窄）
    # ⚠️ 查询串里的中文必须 quote：urllib 不自动编码 query，原样发送直接炸
    from urllib.parse import quote
    # 本轮新端点：/api/govern/stop（0.12.0 时不存在，404 即旧代码）——
    # 无任务时应返回 ok=false 带原因（不是 404/500）
    code, sr = post_json('/api/govern/stop', {}, timeout=30)
    chk('7e 新端点 govern/stop（治理停止入口）',
        code == 200 and (sr or {}).get('ok') is False
        and bool((sr or {}).get('reason')),
        '%s %s' % (code, json.dumps(sr, ensure_ascii=False)[:120]))
    # 0.14.0 新端点：/api/photos/ignore（本次忽略）——无此 id 应 ok 且 updated=0
    code, ir = post_json('/api/photos/ignore', {'photo_ids': ['__no_such__'],
                                                'ignored': True}, timeout=30)
    chk('7f 新端点 photos/ignore（本次忽略）',
        code == 200 and (ir or {}).get('ok') is True
        and (ir or {}).get('updated') == 0,
        '%s %s' % (code, json.dumps(ir, ensure_ascii=False)[:120]))
    ls = http_json('/api/photos/linkstate?container_id=%s&usage=%s'
                   % (cid, quote('监装'))) or {}
    chk('7b linkstate 接收筛选参数', 'all' in ls and ls.get('all', 0) >= 1, ls)

    # 出报告验 A4 纸型
    code, rr = post_json('/api/report/loading-docx', {'container_id': cid})
    path = (rr or {}).get('path')
    chk('8 出报告成功', code == 200 and path, (rr or {}).get('detail') if code != 200 else path)
    if code == 200 and path:
        import zipfile
        docx = path if os.path.isabs(path) else os.path.join(DBHOME, path)
        with zipfile.ZipFile(docx) as z:
            xml = z.read('word/document.xml').decode('utf8')
        m = re.search(r'w:pgSz w:w="(\d+)" w:h="(\d+)"', xml)
        chk('9 docx 纸型 = A4（11909x16834）',
            m is not None and m.group(1) == '11909' and m.group(2) == '16834',
            (m.group(0) if m else 'no pgSz'))

        # 🔴 报告里**必须真有图**（2026-10-20 事故的护栏）：便携化后
        #    photos.path 是相对形态，打包版 exe 的 CWD 不在数据根上，
        #    report_gen 原来用裸 os.path.exists → 满屏 Not provided，
        #    但接口照样 200、docx 照样生成（0 张图），所有老断言全绿。
        #    数 word/media/ 是成本最低的黑盒探针，别删。
        with zipfile.ZipFile(docx) as z:
            n_media = len([f for f in z.namelist()
                           if f.startswith('word/media/')])
        chk('9b 🔴 报告里真的嵌了图片（不是满屏 Not provided）',
            n_media > 0, '%d 张图' % n_media)
finally:
    srv.terminate()
    try:
        _errlog.flush(); _errlog.close()
    except Exception:
        pass
    import shutil as _sh
    tail = open(os.path.join(tempfile.gettempdir(), 'pl_pkgA_exe_err.log'),
                encoding='utf8', errors='replace').read()[-3000:]
    print('---- exe log tail ----')
    print(tail)

print()
print('PASS' if not fails else 'FAIL %d 项' % len(fails))
sys.exit(0 if not fails else 1)
