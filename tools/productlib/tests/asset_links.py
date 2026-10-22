# -*- coding: utf-8 -*-
"""资产化字段（v5 P5）—— 产品来源柜/被引用 + 照片按柜筛选 + 报告柜号解析

背景：产品库、照片库、已生成报告都是**资产** —— 既是这项作业的成果，
也是下一项作业的基础。资产要能回答两个问题：
  · 这个产品从哪来、被谁用过（跨柜复用是它最大的价值）
  · 这个柜有哪些照片 / 出过哪些报告

本测试锁死（直接打路由函数，不打 HTTP —— 锁的是口径不是传输）：
  A 产品 source_container_no = 第一次带它进来的柜
  B 产品 used_by = 引用过它的柜号列表（跨柜复用可视化）
  C has_std 字段存在（标准图有无）
  D GET /api/photos?container_id= 只回该柜照片，不串柜
  E GET /api/batches?container_id= 同上
  F loading-list 的 container_no 从文件名解析，解析不出是 None（不猜）
"""
import os
import sys
import shutil
import tempfile

tmp = tempfile.mkdtemp(prefix='pl_asset_')
# ⚠️ 必须在 import store / routes 之前设：DEFAULT_DB 与 REPORT_DIR 都在导入时算
os.environ['PL_HOME'] = tmp
os.environ['PL_DB'] = os.path.join(tmp, 'asset.db')

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, paths  # noqa: E402
from tools.productlib.routes import products as RP  # noqa: E402
from tools.productlib.routes import photos as RPh  # noqa: E402
from tools.productlib.routes import report as RR  # noqa: E402

con = store.connect()
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


def make_xlsx(path, rows, header=None):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    if header:
        ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)


HDR = ['Part Number', 'DESCRIPTION', 'Package Number',
       'Order Qty', 'Loading Qty', 'Quantity Check result']

# ══════════════════════════════════════════════════════════════════
# 两个柜：A 码两边都有（跨柜复用），B 码只在 c1
# ══════════════════════════════════════════════════════════════════
c1 = store.create_container(con, 'EMCU9914616')
c2 = store.create_container(con, 'MRSU2065286')

cl1 = os.path.join(tmp, 'c1.xlsx')
make_xlsx(cl1, [['216070000001', 'CONTAINER, MANUAL STORAGE', 'Cage-M068', '12', '12', 'PASS'],
                ['105021020095B', 'TANK, FUEL', 'Pallet-M56', '20', '20', 'PASS']], HDR)
store.import_checklist_file(con, cl1, container_id=c1['id'])

cl2 = os.path.join(tmp, 'c2.xlsx')
make_xlsx(cl2, [['216070000001', 'CONTAINER, MANUAL STORAGE', 'Cage-M068', '5', '5', 'PASS']], HDR)
store.import_checklist_file(con, cl2, container_id=c2['id'])

# ══════════════════════════════════════════════════════════════════
# A / B / C 产品资产字段
# ══════════════════════════════════════════════════════════════════
items = RP.api_products(limit=200)['items']
chk('A0 两个产品都在列表里', len(items) >= 2, [r['code_norm'] for r in items])


def find(sub):
    for r in items:
        if sub in r['code_norm']:
            return r
    return None


a = find('216070000001')
b = find('105021020095B')
chk('A0b 两个编码都取到了', a is not None and b is not None)
chk('A1 来源柜 = 第一次带它进来的柜（c1）',
    a['source_container_no'] == 'EMCU9914616', a['source_container_no'])
# used_by 的 SQL 顺序不保证，用集合比
chk('B1 被引用 = 两个柜（跨柜复用看得见）',
    set(a['used_by']) == {'EMCU9914616', 'MRSU2065286'}, a['used_by'])
chk('B2 只在 c1 的产品只被 1 个柜引用',
    b['used_by'] == ['EMCU9914616'], b['used_by'])
chk('C1 has_std 字段存在（还没标准图 → False）',
    'has_std' in a and a['has_std'] is False, a.get('has_std'))
chk('C2 每一行都带三个资产字段（不缺列）',
    all(('source_container_no' in r and 'used_by' in r and 'has_std' in r) for r in items))

# ══════════════════════════════════════════════════════════════════
# D 照片按柜筛选
# ══════════════════════════════════════════════════════════════════
from PIL import Image  # noqa: E402


def mkimgs(d, n, color, prefix):
    """造测试照片。⚠️ 两个柜必须用**不同文件名** —— photos.file 有 UNIQUE
    约束，去重认文件名（不只是 MD5）。同名不同内容的文件会被判成重复静默跳过，
    「c2 一张都没进」就是这么来的（不是 bug，是既有的去重口径）。"""
    os.makedirs(d, exist_ok=True)
    for i in range(n):
        # 尺寸随 i 变 —— 保证字节不同
        Image.new('RGB', (60 + i, 40), color).save(
            os.path.join(d, '%s%02d.jpg' % (prefix, i)))


d1 = os.path.join(tmp, 'ph1')
d2 = os.path.join(tmp, 'ph2')
mkimgs(d1, 3, (10, 20, 30), 'c1_')
mkimgs(d2, 2, (200, 10, 10), 'c2_')
ap1 = store.add_photos(con, d1, container_id=c1['id'])
ap2 = store.add_photos(con, d2, container_id=c2['id'])

r1 = RPh.api_photos(container_id=c1['id'], limit=200)
r2 = RPh.api_photos(container_id=c2['id'], limit=200)
rall = RPh.api_photos(limit=200)
chk('D1 c1 只回 3 张', r1['total'] == 3, r1['total'])
chk('D2 c2 只回 2 张', r2['total'] == 2, r2['total'])
chk('D3 不传柜 = 全库 5 张', rall['total'] == 5, rall['total'])
ids1 = {p['id'] for p in r1['items']}
ids2 = {p['id'] for p in r2['items']}
chk('D4 两柜照片不串（交集为空）', not (ids1 & ids2), ids1 & ids2)
chk('D5 传了柜就只回该柜（不是子集交集）', ids1 and ids2 and ids1.isdisjoint(ids2))

# ══════════════════════════════════════════════════════════════════
# E 批次按柜筛选
# ══════════════════════════════════════════════════════════════════
b1 = RPh.api_batches(container_id=c1['id'])['items']
b2 = RPh.api_batches(container_id=c2['id'])['items']
chk('E1 按柜筛批次：c1 只有 1 个照片批次',
    len(b1) == 1 and b1[0]['id'] == ap1['batch_id'], [x['id'] for x in b1])
chk('E2 按柜筛批次：c2 只有 1 个照片批次',
    len(b2) == 1 and b2[0]['id'] == ap2['batch_id'], [x['id'] for x in b2])

# ══════════════════════════════════════════════════════════════════
# F 报告柜号从文件名解析（零表、零迁移）
# ══════════════════════════════════════════════════════════════════
rdir = paths.reports_dir()
os.makedirs(rdir, exist_ok=True)
F1 = 'LOADING REPORT-CNTR#EMCU9914616-20261006-1020.docx'
F2 = 'LOADING REPORT-CNTR#MRSU2065286-20261005-0900.docx'
F3 = 'notes.docx'          # 没有 CNTR# —— 柜号必须是 None，不许瞎猜
for fn in (F1, F2, F3):
    with open(os.path.join(rdir, fn), 'wb') as f:
        f.write(b'PK\x03\x04' + b'x' * 120)

lst = RR.api_loading_list()['items']
by = {x['name']: x for x in lst}
chk('F1 报告柜号从文件名解析（c1）',
    by.get(F1, {}).get('container_no') == 'EMCU9914616', by.get(F1))
chk('F2 报告柜号从文件名解析（c2）',
    by.get(F2, {}).get('container_no') == 'MRSU2065286', by.get(F2))
chk('F3 解析不出柜号 = None（不猜）', F3 in by and by[F3]['container_no'] is None,
    by.get(F3))
chk('F4 三份都在列表里', len(lst) == 3, [x['name'] for x in lst])
chk('F5 total_bytes 有值', RR.api_loading_list()['total_bytes'] > 0)

con.close()
shutil.rmtree(tmp, ignore_errors=True)

print('\n%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
