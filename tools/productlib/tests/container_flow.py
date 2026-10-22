# -*- coding: utf-8 -*-
"""柜号主线（v3）：柜实体 / 无柜不导闸门 / 清单行快照 / 监装标签 / 箱号路径提取

背景（2026-10-05 老板拍板）：
  ① 柜号是唯一主线 —— 批次、照片导入、清单导入全按柜号走，
     **必须先确定柜号才能进入后续流程**（建柜→清单→照片→治理→报告）；
  ② 照片尺寸/排版方向的处理时机要明确（治理绝不碰像素，报告生成负责版面）。

本测试锁死：
  A 柜 CRUD + 柜号唯一（重复建柜报错，不静默合并）
  B 老数据归柜：container_no 分组建柜 + 空柜号挂「未分柜」兜底 + 可改挂
  C 迁移幂等：连跑两次 _migrate 不炸（ADD COLUMN 不幂等会锁死库）
  D 闸门：无 container_id 的导入一律 ContainerError
  E 清单行快照：原行不合并（同码 3 行 = 3 行）、Order/Loading/Check 三列落库、
     数量存文本照抄、重导整批替换
  F 箱号从 App 交付包路径自动提取（预检/{箱号}/x.jpg），_未分箱 不猜
  G 监装标签：7 类合法校验 + 批量打 + 只写元数据不碰像素
"""
import os
import sys
import json
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
# ⚠️ 顺序要紧：store.py 自己会把 tools/ 塞进 sys.path，build_library 才能被
#    import（它在 tools/build_library.py，不在仓库根）。先 import store。
from tools.productlib import store, schema  # noqa: E402
import build_library as BL  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_container_')
con = store.connect(os.path.join(tmp, 't.db'))
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


# ══════════════════════════════════════════════════════════════════
# A 柜 CRUD + 柜号唯一
# ══════════════════════════════════════════════════════════════════
c1 = store.create_container(con, 'EMCU9914616', seal_no='EMCEXE7565',
                           inspector='Jerry Xu')
chk('A1 建柜返回 id + 柜号', c1['id'] and c1['container_no'] == 'EMCU9914616', c1['id'])
chk('A2 柜元数据落库', c1['seal_no'] == 'EMCEXE7565' and c1['inspector'] == 'Jerry Xu')

try:
    store.create_container(con, 'EMCU9914616')
    chk('A3 柜号重复应报错', False, '居然建成功了')
except store.ContainerError as e:
    chk('A3 柜号重复应报错', '已存在' in str(e), str(e))

try:
    store.create_container(con, '  ')
    chk('A4 空柜号应报错', False)
except store.ContainerError:
    chk('A4 空柜号应报错', True)

upd = store.update_container(con, c1['id'], location='Changsha City', remark='')
chk('A5 改元数据 + 空串清空', upd['location'] == 'Changsha City' and upd['remark'] is None,
    'remark=%r' % upd['remark'])

lst = store.list_containers(con)
chk('A6 柜列表带出统计字段',
    len(lst) == 1 and 'checklist_rows' in lst[0] and 'supervision' in lst[0])

# ══════════════════════════════════════════════════════════════════
# D 闸门：无柜不导（先测这个，它是 v3 的核心约束）
# ══════════════════════════════════════════════════════════════════
try:
    store.add_photos(con, tmp, container_id=None)
    chk('D1 照片导入无柜应拒', False)
except store.ContainerError as e:
    chk('D1 照片导入无柜应拒', '请先选择柜' in str(e), str(e))

try:
    store.import_checklist_file(con, __file__, container_id=None)
    chk('D2 清单导入无柜应拒', False)
except store.ContainerError as e:
    chk('D2 清单导入无柜应拒', '请先选择柜' in str(e), str(e))

# ══════════════════════════════════════════════════════════════════
# E 清单行快照 —— 需要真 xlsx，造一个最小清单
# ══════════════════════════════════════════════════════════════════
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
# 同码 3 行（报告里是 3 件）+ 另一个码 2 行
ROWS = [
    ['216070000001', 'CONTAINER, MANUAL STORAGE', 'Cage-M068', '12', '12', 'PASS'],
    ['216070000001', 'CONTAINER, MANUAL STORAGE', 'Cage-M068', '12', '12', 'PASS'],
    ['216070000001', 'CONTAINER, MANUAL STORAGE', 'Cage-M068', '12', '12', 'PASS'],
    ['105021020095B', 'TANK, FUEL', 'Pallet-M56', '20', '20', 'PASS'],
    ['105021020095B', 'TANK, FUEL', 'Pallet-M56', '20', '20', 'PASS'],
]
cl_path = os.path.join(tmp, 'EMCU9914616.xlsx')
make_xlsx(cl_path, ROWS, HDR)

r = store.import_checklist_file(con, cl_path, container_id=c1['id'])
chk('E1 清单导入挂柜', r.get('container_id') == c1['id'], r.get('batch_id'))
chk('E2 行快照按原行落库（同码不合并）', r['snap_rows'] == 5, 'snap_rows=%s' % r['snap_rows'])
chk('E3 合并视图仍是 2 个产品', r['parsed'] == 2, 'parsed=%s' % r['parsed'])

snap = store.checklist_rows_of(con, r['batch_id'])
chk('E4 快照保留 Package Number 箱号', snap[0]['package_no'] == 'Cage-M068',
    snap[0]['package_no'])
chk('E5 三列都落库',
    snap[0]['order_qty'] == '12' and snap[0]['loading_qty'] == '12'
    and snap[0]['check_import'] == 'PASS')
chk('E6 同码多行 seq 各不相同',
    [s['seq'] for s in snap] == [1, 2, 3, 4, 5], [s['seq'] for s in snap])
chk('E7 check_result 初始为 NULL（未核对）',
    all(s['check_result'] is None for s in snap))

# 数量列存文本照抄：'12.0' 不许被转成 12
ROWS2 = [['216070000001', 'X', 'Cage-M068', '12.0', '12.0', ''],
         ['216070000001', 'X', 'Cage-M068', '12.0', '12.0', '']]
cl2 = os.path.join(tmp, 'qty_text.xlsx')
make_xlsx(cl2, ROWS2, HDR)
r2 = store.import_checklist_file(con, cl2, container_id=c1['id'])
s2 = store.checklist_rows_of(con, r2['batch_id'])
chk('E8 数量列文本照抄（12.0 不被转成 12）', s2[0]['order_qty'] == '12.0',
    repr(s2[0]['order_qty']))

# 人工核对：只写 check_result，check_import 保留；空值 = 沿用预填
store.set_row_check(con, r['batch_id'], 1, 'FAIL', loading_qty='10')
s1 = store.checklist_rows_of(con, r['batch_id'])[0]
chk('E9 人工核对写 check_result + Loading Qty',
    s1['check_result'] == 'FAIL' and s1['loading_qty'] == '10')
chk('E10 清单预填值仍在（未被覆盖）', s1['check_import'] == 'PASS')
store.set_row_check(con, r['batch_id'], 1, '')
s1b = store.checklist_rows_of(con, r['batch_id'])[0]
chk('E11 清空核对 = 回到未核对（沿用预填）', s1b['check_result'] is None)

# 重导同柜清单 → 整批替换，不叠加
r3 = store.import_checklist_file(con, cl_path, container_id=c1['id'])
n_batches = con.execute("SELECT COUNT(*) FROM batches WHERE container_id=? AND kind='checklist'",
                        (c1['id'],)).fetchone()[0]
chk('E12 重导是新建批次（每批一份快照）', n_batches == 3, 'batches=%s' % n_batches)
chk('E13 每个批次各有 5 行快照', r3['snap_rows'] == 5)

# ══════════════════════════════════════════════════════════════════
# F 箱号从 App 交付包路径自动提取
# ══════════════════════════════════════════════════════════════════
chk('F1 预检/{箱号}/x.jpg 提取到箱号',
    store.carton_from_relpath('预检/箱A/P_20260927_1.jpg', 'root') == '箱A',
    store.carton_from_relpath('预检/箱A/P_20260927_1.jpg', 'root'))
chk('F2 Windows 反斜杠也认',
    store.carton_from_relpath(r'预检\Cage-M239\x.jpg', 'root') == 'Cage-M239')
chk('F3 _未分箱 不猜（返回 None）',
    store.carton_from_relpath('预检/_未分箱/x.jpg', 'root') is None)
chk('F4 监装目录不产生箱号',
    store.carton_from_relpath('监装/P_1.jpg', 'root') is None)
chk('F5 没带 root 时用全路径也能提',
    store.carton_from_relpath('D:/交付/预检/箱B/a.jpg') == '箱B')

# 造真照片目录走一遍 add_photos（验证 carton_no 真的落库）
from PIL import Image  # noqa: E402
deliv = os.path.join(tmp, '交付', '预检', 'Cage-M239')
os.makedirs(deliv, exist_ok=True)
for i in range(2):
    Image.new('RGB', (60, 40), (i * 40, 80, 120)).save(
        os.path.join(deliv, 'P_20260927_%02d.jpg' % i))
sup = os.path.join(tmp, '交付', '监装')
os.makedirs(sup, exist_ok=True)
for i in range(2):
    Image.new('RGB', (50, 50), (200, i * 30, 60)).save(
        os.path.join(sup, 'P_20260927_%02d.jpg' % i))

root = os.path.join(tmp, '交付')
ap = store.add_photos(con, root, container_id=c1['id'])
rows = list(con.execute("SELECT file,carton_no FROM photos WHERE batch_id=?",
                        (ap['batch_id'],)))
cartons = {x['carton_no'] for x in rows}
# 4 张必须**全部**入库（预检 2 + 监装 2）。改 file 存相对路径之前，
# 同名文件会被 UNIQUE 约束静默吞掉，added 只有 2 —— 这条断言就是守它的。
chk('F6 预检/监装同名文件全部入库（不静默丢照片）',
    ap['added'] == 4 and len(rows) == 4, 'added=%s rows=%s' % (ap['added'], len(rows)))
chk('F7 预检照片箱号自动提取为 Cage-M239', cartons == {None, 'Cage-M239'}, cartons)
chk('F8 监装照片不编造箱号', None in cartons)
chk('F9 file 存相对路径（可追溯到箱号目录）',
    any(x['file'].startswith('预检/Cage-M239/') for x in rows),
    [x['file'] for x in rows])
chk('F10 批次挂柜', con.execute(
    'SELECT container_id FROM batches WHERE id=?', (ap['batch_id'],)
).fetchone()[0] == c1['id'])

# ══════════════════════════════════════════════════════════════════
# G 监装标签
# ══════════════════════════════════════════════════════════════════
# 监装照片 = file 以「监装/」开头的那几张（先标 usage，与柜详情页的动作一致）
sup_ids = [x['id'] for x in con.execute(
    "SELECT id FROM photos WHERE batch_id=? AND file LIKE '监装/%'",
    (ap['batch_id'],))]
chk('G0 监装照片筛出来了', len(sup_ids) == 2, sup_ids)
# 柜详情页的动作是**批量**标用途与标签（监装是连拍流，逐张点会点断手）
for pid in sup_ids:
    store.set_photo_usage(con, pid, '监装')
sup_ids = [x['id'] for x in con.execute(
    "SELECT id FROM photos WHERE batch_id=? AND photo_usage='监装'", (ap['batch_id'],))]

n = store.set_supervision_tag(con, sup_ids, 'container_seal')
chk('G1 批量打标签', n == len(sup_ids) and len(sup_ids) == 2,
    'n=%s ids=%s' % (n, len(sup_ids)))
try:
    store.set_supervision_tag(con, sup_ids, '不存在的标签')
    chk('G2 非法标签应报错', False)
except ValueError as e:
    chk('G2 非法标签应报错', '标签只能是' in str(e))

# 只写元数据：标签前后像素字节数必须完全一致
pid0 = sup_ids[0]
before = open(con.execute('SELECT path FROM photos WHERE id=?', (pid0,)).fetchone()[0], 'rb').read()
store.set_supervision_tag(con, [pid0], 'truck_head')
after = open(con.execute('SELECT path FROM photos WHERE id=?', (pid0,)).fetchone()[0], 'rb').read()
chk('G3 打标签不碰像素（治理绝不改原图）', before == after,
    '%d vs %d bytes' % (len(before), len(after)))

cnt = store.batch_supervision_tags(con)
chk('G4 标签计数', cnt.get('truck_head') == 1, cnt)

# ══════════════════════════════════════════════════════════════════
# 柜详情聚合面板
# ══════════════════════════════════════════════════════════════════
d = store.container_detail(con, c1['id'])
chk('H1 详情聚合：批次列表', len(d['batches']) == 4, len(d['batches']))
# 三批快照 = 5(PASS 预填) + 2(check_import 为空的清单) + 5(PASS 预填)
chk('H2 详情聚合：行总数 = 5+2+5', d['row_total'] == 12, d['row_total'])
# 未核对 = check_result 与 check_import **都**空的行 —— qty_text 那张清单的
# 2 行没预填核对结果，所以是 2；预填了 PASS 的不算未核对（那是客户的数据）
chk('H3 详情聚合：未核对数只算「两列皆空」', d['row_unchecked'] == 2,
    d['row_unchecked'])
chk('H4 详情聚合：照片按用途分布',
    d['photo_stats'].get('监装') == 2 and d['photo_stats'].get('未分类') == 2,
    d['photo_stats'])
chk('H5 详情聚合：柜况代表图取该 tag 最新一张',
    (d['condition_photos']['container_seal'] or {}).get('id') in sup_ids,
    d['condition_photos']['container_seal'])
chk('H6 详情聚合：没照片的柜况槽位是 None（不留空壳）',
    d['condition_photos']['container_lock'] is None)

# ══════════════════════════════════════════════════════════════════
# B/C 老数据归柜 + 迁移幂等（独立库，模拟老库）
# ══════════════════════════════════════════════════════════════════
old = tempfile.mkdtemp(prefix='pl_old_')
old_db = os.path.join(old, 'old.db')
ocon = store.connect(old_db)
# 造一个「v2 之前」的库：batches 只有 container_no，没有 containers 行
ocon.execute("INSERT INTO containers(id,container_no,created_at,updated_at)"
             " VALUES('x','_PRE_','2026-01-01','2026-01-01')")
ocon.execute("DELETE FROM containers WHERE id='x'")
ocon.execute("INSERT INTO batches(id,kind,name,container_no,item_count,created_at)"
             " VALUES('b1','photos','照片A','EMCU9914616',0,'2026-01-01')")
ocon.execute("INSERT INTO batches(id,kind,name,container_no,item_count,created_at)"
             " VALUES('b2','photos','照片B','',0,'2026-01-01')")
ocon.execute("INSERT INTO batches(id,kind,name,container_no,item_count,created_at)"
             " VALUES('b3','checklist','清单A','MRSU2065286',0,'2026-01-01')")
# 把 containers 清空到只剩兜底，模拟「归柜前」状态
ocon.execute("UPDATE batches SET container_id=NULL")
# 手工清掉自动建出来的柜，回到迁移前
rows = ocon.execute("SELECT id FROM containers").fetchall()
for r0 in rows:
    ocon.execute("DELETE FROM containers WHERE id=?", (r0['id'],))
ocon.commit()
# 触发一次迁移
store._migrate(ocon)
m1 = {r['container_no']: r['id'] for r in ocon.execute('SELECT * FROM containers')}
chk('B1 老批次按柜号自动建柜',
    'EMCU9914616' in m1 and 'MRSU2065286' in m1, list(m1))
chk('B2 空柜号批次挂未分柜兜底', schema.UNCATEGORIZED_NO in m1, list(m1))
bmap = {r['id']: r['container_id'] for r in ocon.execute('SELECT * FROM batches')}
chk('B3 批次回填 container_id', bmap['b1'] == m1['EMCU9914616'], bmap)
chk('B4 空柜号批次进兜底柜', bmap['b2'] == m1[schema.UNCATEGORIZED_NO], bmap)

# C 幂等：再跑一次不炸、不重复建柜
n_before = ocon.execute('SELECT COUNT(*) FROM containers').fetchone()[0]
store._migrate(ocon)
store._migrate(ocon)
n_after = ocon.execute('SELECT COUNT(*) FROM containers').fetchone()[0]
chk('C1 迁移连跑三次不炸且不重复建柜', n_before == n_after, '%s -> %s' % (n_before, n_after))

# 改挂：补柜号后把批次挪到正式柜
newc = store.create_container(ocon, 'EMCU9999999')
store.assign_batch_container(ocon, 'b2', newc['id'])
got = ocon.execute('SELECT container_id,container_no FROM batches WHERE id=?',
                   ('b2',)).fetchone()
chk('B5 批次可改挂到正式柜（container_no 同步）',
    got['container_id'] == newc['id'] and got['container_no'] == 'EMCU9999999',
    dict(got))

# 兜底柜不该出现在「柜下拉」的业务语义里，但列表要能看见（提示补柜号）
lst2 = store.list_containers(ocon)
unc = [x for x in lst2 if x['is_uncategorized']]
chk('B6 兜底柜在列表里带 is_uncategorized 标记', len(unc) == 1, [x['container_no'] for x in lst2])

ocon.close()
con.close()
shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(old, ignore_errors=True)

print('\n%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
