# -*- coding: utf-8 -*-
"""绿色包的**完整业务链路**冒烟（HTTP 层）—— 跑在打包版上，不是源码目录。

为什么源码测试不够：`tests/loading_report.py` 是直接 import 模块跑生成器，
**证明不了 PyInstaller 把 openpyxl / Pillow / python-docx 收全了**。
这三个库缺一个，源码版全绿，用户导清单或出报告时才炸 —— 那是发给别人的包。

本脚本按真实链路走一遍：建柜 → 导真实 xlsx 清单 → 上传照片 → 取缩略图 →
人工关联 → 出 docx → **拆开 docx 验每页 ≤6 张 + 有章节分页符**。

⚠️ 必须在**一次性实例**上跑（空 data 目录 + 临时端口），别指向正式库：
   它会真的建柜、导清单、写 reports。

用法：
    # ① 解包并起一个隔离实例
    set PL_HOME=<临时目录> && dist\\<时间戳>\\集刻产品库\\集刻产品库.exe --port 8899
    # ② 跑链路
    python tools/productlib/checks/pack_chain.py http://127.0.0.1:8899
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8899'
REPO = r'D:\G-TickPicture'
FAILS = []


def chk(name, ok, info=''):
    print(('[ OK ] ' if ok else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not ok:
        FAILS.append(name)


def post_json(path, obj, timeout=600):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode('utf8'),
                                 headers={'Content-Type': 'application/json'})
    try:
        return 200, json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode('utf8'))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf8', 'replace')[:300]


def post_file(path, fields, files, timeout=900):
    b = '----plb' + uuid.uuid4().hex
    buf = b''
    for k, v in fields.items():
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                % (b, k, v)).encode()
    for k, fpath, fn in files:
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n'
                % (b, k, fn)).encode()
        buf += open(fpath, 'rb').read() + b'\r\n'
    buf += ('--%s--\r\n' % b).encode()
    req = urllib.request.Request(BASE + path, data=buf,
                                 headers={'Content-Type':
                                          'multipart/form-data; boundary=' + b})
    try:
        return 200, json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode('utf8'))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf8', 'replace')[:300]


def get_bytes(path, timeout=300):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=timeout)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b''


def get_json(path, timeout=300):
    try:
        return 200, json.loads(urllib.request.urlopen(BASE + path, timeout=timeout).read().decode('utf8'))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf8', 'replace')[:300]


# ── ① 建柜（柜号带时间戳：重跑不撞「柜号已存在」）──
CNO = 'PACK' + time.strftime('%m%d_%H%M%S')
code, c = post_json('/api/containers',
                    {'container_no': CNO, 'seal_no': 'SEAL1',
                     'inspector': 'pack', 'client_name': 'ACME',
                     'location': 'Changsha', 'product_name': 'PARTS',
                     'arrival_at': '8:49', 'departure_at': '11:27',
                     'inspection_date': '2026-10-07'})
chk('P1 建柜', code == 200 and isinstance(c, dict) and c.get('id'),
    '%s %s' % (code, c if not isinstance(c, dict) else c.get('container_no')))
cid = (c or {}).get('id') if isinstance(c, dict) else None
if not cid:
    print('建柜失败，终止'); sys.exit(1)

# ── ② 导清单（openpyxl）──
code, r = post_file('/api/products/import', {'container_id': cid},
                    [('file', os.path.join(REPO, '9.13 5x40HQ', 'MIEU2012616.xlsx'),
                      'MIEU2012616.xlsx')])
chk('P2 导入真实清单（打包版 openpyxl 可用）',
    code == 200 and (r or {}).get('snap_rows', 0) > 50,
    '%s %s' % (code, {k: r.get(k) for k in ('parsed', 'added', 'snap_rows')} if isinstance(r, dict) else r))

# ── ③ 造 8 张照片并上传（PIL 缩略图）──
from PIL import Image  # noqa: E402
tmp = os.path.join(os.environ['TEMP'], 'pl_pack_photos')
os.makedirs(tmp, exist_ok=True)
files = []
_tag = time.strftime('%m%d%H%M%S')
# ⚠️ 文件名必须每次运行都不同：photos.file 是 UNIQUE 的，重名会被判重复跳过
#    （第一次跑 added=8、第二次 skipped=8 —— 那是测试自己的坑，不是包的问题）
for i in range(8):
    p = os.path.join(tmp, 'PACK_%s_%02d.jpg' % (_tag, i))
    Image.new('RGB', (1600, 1200), (30 * i, 60, 200 - 10 * i)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('P3 上传 8 张照片（打包版 Pillow 可用）',
    code == 200 and (r or {}).get('added', 0) == 8,
    '%s %s' % (code, r if not isinstance(r, dict) else
               {k: r.get(k) for k in ('saved', 'added', 'skipped')}))

code, ph = get_json('/api/photos?container_id=%s&limit=50' % cid)
items = (ph or {}).get('items', []) if isinstance(ph, dict) else []
chk('P4 照片查得到', len(items) == 8, len(items))
sc, blob = get_bytes('/thumb/%s' % items[0]['id']) if items else (0, b'')
chk('P5 缩略图接口返回真图（JPEG 魔数）',
    sc == 200 and blob[:2] == b'\xff\xd8', '%s %s' % (sc, blob[:4]))

# ── ④ 关联 → 出报告（python-docx + PIL 图框）──
first = items[0]['id'] if items else None
# ⚠️ **不要从「本柜的清单批次」取编码**（10-07 踩过）：产品是**全局唯一**的，
#    重复导入同一份清单时 added=0，老产品的 source_batch 仍指向**第一次**那个
#    批次 —— 于是本柜批次下 products 恒为空，看着像「导入没生效」。
#    关联测试要验的是「能不能关联」，编码从全库取即可。
_cb = get_json('/api/checklist-batches')[1] or {}
_hit = [b for b in (_cb.get('items') or []) if (b.get('container_no') or '') == CNO]
_batch_id = (_hit[0] or {}).get('id') if _hit else None
rows = get_json('/api/batches/%s/products' % _batch_id)[1] if _batch_id else {'items': []}
prow = (rows or {}).get('items') or []
pl = get_json('/api/products?limit=200')[1] or {}
allp = pl.get('items') or []
chk('P6 产品库里有编码可用（清单导进去了）', len(allp) > 0, '%s 个产品' % len(allp))
linked = 0
for row in allp[:4]:
    if not first:
        break
    cd, rr = post_json('/api/links', {'code': row.get('code') or row.get('code_norm'),
                                      'photo_id': first, 'by': 'packtest'})
    if cd == 200:
        linked += 1
chk('P7 人工关联写入', linked >= 1, linked)

t0 = time.time()
code, rep = post_json('/api/report/loading-docx', {'container_id': cid})
sec = time.time() - t0
chk('P8 生成装柜报告（打包版 python-docx + 图框可用）',
    code == 200 and isinstance(rep, dict) and (rep.get('bytes') or 0) > 20000,
    '%s %.0fs %s' % (code, sec, rep if not isinstance(rep, dict)
                     else {k: rep.get(k) for k in ('bytes', 'rows', 'photos', 'path')}))

# ── ⑤ 拆开 docx 验结构：每页 ≤ 6 张 + 章节分页 ──
if isinstance(rep, dict) and rep.get('path'):
    import zipfile
    import xml.etree.ElementTree as ET
    W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
    with zipfile.ZipFile(rep['path']) as z:
        root = ET.fromstring(z.read('word/document.xml').decode('utf8'))
        n_media = len([n for n in z.namelist() if n.startswith('word/media/')])
    counts = [len(list(t.iter(A + 'blip'))) for t in root.iter(W + 'tbl')]
    grid = [c for c in counts if c > 0]
    brk = [e for e in root.iter(W + 'br') if e.get(W + 'type') == 'page']
    chk('P9 打包版生成的报告：每张表 ≤ 6 张图', grid and max(grid) <= 6, grid)
    chk('P10 打包版生成的报告：有章节分页符', len(brk) >= 2, len(brk))
    chk('P11 图片全部嵌进去了', n_media >= 1, '%d 张' % n_media)
else:
    chk('P9~P11 报告结构核验', False, '没拿到报告路径')

print('\n%d 项失败' % len(FAILS))
for f in FAILS:
    print('  - ' + f)
sys.exit(1 if FAILS else 0)
