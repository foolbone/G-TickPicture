# -*- coding: utf-8 -*-
"""作业向导五步就绪度（v5 P3）—— store.container_progress

背景：向导的每一步状态**全部派生自数据**（行数 / 治理数 / 报告文件数），
不落 localStorage 记账。关掉浏览器回来还是那一步，换台机器也不会漂。
所以这里的断言就是「派生的口径」本身 —— 改口径前先看这些断言同不同意。

本测试锁死：
  A 空柜：只有①完成（ready 20），缺的元数据要点名
  B 只导清单：②完成（+15 → 35），未核对只算「check_result 与 check_import 皆空」
  C 再导照片：③完成（+15 → 50）
  D 治理跑完：④完成（+25 → 75）
  E 出报告：⑤完成（+25 → 100）；别柜的报告不许串到这个柜头上
  F 未分柜：①不算完成（老数据还没归柜，这是①该提示的事）
  G 待确认数：只数「本柜清单里的编码」且 review_state 未 confirmed 的产品
"""
import os
import sys
import shutil
import tempfile

tmp = tempfile.mkdtemp(prefix='pl_wizard_')
# ⚠️ 必须在 import store 之前设：store.DEFAULT_DB / paths 都在导入时算
os.environ['PL_HOME'] = tmp
os.environ['PL_DB'] = os.path.join(tmp, 'wiz.db')

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, schema, paths  # noqa: E402

con = store.connect()
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


def prog(cid):
    return store.container_progress(con, cid)


# ══════════════════════════════════════════════════════════════════
# A 空柜
# ══════════════════════════════════════════════════════════════════
c1 = store.create_container(con, 'EMCU9914616', seal_no='EMCEXE7565')
p = prog(c1['id'])
chk('A1 空柜：①完成（已建柜、不是未分柜）', p['steps']['container']['done'] is True)
chk('A2 空柜：②未开始', p['steps']['checklist']['done'] is False
    and p['steps']['checklist']['row_total'] == 0)
chk('A3 空柜：③未开始', p['steps']['photos']['done'] is False
    and p['steps']['photos']['total'] == 0)
chk('A4 空柜：④未开始', p['steps']['govern']['done'] is False)
chk('A5 空柜：⑤未开始', p['steps']['report']['done'] is False
    and p['steps']['report']['files'] == 0)
chk('A6 就绪度 = ①的 20%', p['ready_pct'] == 20, p['ready_pct'])
# ①要把「缺什么」点名（进报告 General Information 的字段）
mm = p['meta_missing']
chk('A7 缺项点名：填了封条 → 缺 inspector/client/location',
    set(mm) == {'inspector', 'client_name', 'location'}, mm)
chk('A8 ①的 summary 是柜号', p['steps']['container']['summary'] == 'EMCU9914616',
    p['steps']['container']['summary'])

# ══════════════════════════════════════════════════════════════════
# B 只导清单
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
# 第一行预填 PASS（客户的数，不算我们核对过），第二行空 → 未核对
ROWS = [['216070000001', 'CONTAINER, MANUAL STORAGE', 'Cage-M068', '12', '12', 'PASS'],
        ['105021020095B', 'TANK, FUEL', 'Pallet-M56', '20', '20', '']]
cl = os.path.join(tmp, 'EMCU9914616.xlsx')
make_xlsx(cl, ROWS, HDR)
store.import_checklist_file(con, cl, container_id=c1['id'])

p = prog(c1['id'])
chk('B1 导清单后②完成', p['steps']['checklist']['done'] is True)
chk('B2 清单行 = 2', p['steps']['checklist']['row_total'] == 2,
    p['steps']['checklist']['row_total'])
chk('B3 未核对只算「两列皆空」（预填 PASS 的不算）',
    p['steps']['checklist']['row_unchecked'] == 1, p['steps']['checklist']['row_unchecked'])
chk('B4 清单批次 = 1', p['steps']['checklist']['batches'] == 1,
    p['steps']['checklist']['batches'])
chk('B5 就绪度 20+15 = 35', p['ready_pct'] == 35, p['ready_pct'])

# ══════════════════════════════════════════════════════════════════
# C 再导照片
# ══════════════════════════════════════════════════════════════════
from PIL import Image  # noqa: E402

deliv = os.path.join(tmp, '交付', '预检', 'Cage-M239')
os.makedirs(deliv, exist_ok=True)
for i in range(3):
    Image.new('RGB', (60, 40), (i * 40, 80, 120)).save(
        os.path.join(deliv, 'P_20260927_%02d.jpg' % i))
ap = store.add_photos(con, os.path.join(tmp, '交付'), container_id=c1['id'])

p = prog(c1['id'])
chk('C1 导照片后③完成', p['steps']['photos']['done'] is True)
chk('C2 照片 = 3 张', p['steps']['photos']['total'] == 3, p['steps']['photos']['total'])
chk('C3 照片批次 = 1', p['steps']['photos']['batches'] == 1, p['steps']['photos']['batches'])
chk('C4 就绪度 20+15+15 = 50', p['ready_pct'] == 50, p['ready_pct'])
chk('C5 ③还没治理时④仍不算完成', p['steps']['govern']['done'] is False)

# ══════════════════════════════════════════════════════════════════
# D 治理跑完
# ══════════════════════════════════════════════════════════════════
con.execute("UPDATE photos SET govern_state='done'")
con.commit()
p = prog(c1['id'])
chk('D1 治理跑完④完成', p['steps']['govern']['done'] is True)
chk('D2 已治理 3/3', p['steps']['govern']['summary'] == '3/3 已治理',
    p['steps']['govern']['summary'])
chk('D3 待治理 0 / 失败 0', p['steps']['govern']['pending'] == 0
    and p['steps']['govern']['failed'] == 0)
chk('D4 就绪度 50+25 = 75', p['ready_pct'] == 75, p['ready_pct'])

# ══════════════════════════════════════════════════════════════════
# E 出报告（报告文件从文件名 CNTR#<柜号> 认领，零表零迁移）
# ══════════════════════════════════════════════════════════════════
rdir = paths.reports_dir()
os.makedirs(rdir, exist_ok=True)
with open(os.path.join(rdir, 'LOADING REPORT-CNTR#EMCU9914616-20261006-1020.docx'), 'wb') as f:
    f.write(b'PK\x03\x04' + b'x' * 200)

p = prog(c1['id'])
chk('E1 出报告后⑤完成', p['steps']['report']['done'] is True)
chk('E2 报告份数 = 1', p['steps']['report']['files'] == 1, p['steps']['report']['files'])
chk('E3 就绪度 75+25 = 100', p['ready_pct'] == 100, p['ready_pct'])

# 别柜的报告不许算到这个柜头上（认领靠柜号，不是「有文件就算」）
with open(os.path.join(rdir, 'LOADING REPORT-CNTR#OTHER9999999-20261006-0900.docx'), 'wb') as f:
    f.write(b'PK\x03\x04' + b'y' * 200)
with open(os.path.join(rdir, 'notes.docx'), 'wb') as f:
    f.write(b'PK\x03\x04' + b'z' * 200)
p = prog(c1['id'])
chk('E4 别柜报告不串柜（仍 1 份）', p['steps']['report']['files'] == 1,
    p['steps']['report']['files'])

# ══════════════════════════════════════════════════════════════════
# F 未分柜：①不算完成（老数据的兜底柜，①要提示补柜号）
# ══════════════════════════════════════════════════════════════════
unc_row = con.execute(
    "SELECT id FROM containers WHERE container_no=?", (schema.UNCATEGORIZED_NO,)).fetchone()
if unc_row:
    unc_id = unc_row['id']
else:
    unc_id = 'c-unc-test'
    con.execute("INSERT INTO containers(id,container_no,created_at,updated_at)"
                " VALUES(?,?,'2026-01-01','2026-01-01')", (unc_id, schema.UNCATEGORIZED_NO))
    con.commit()
pu = prog(unc_id)
chk('F1 未分柜：①不算完成', pu['steps']['container']['done'] is False)
chk('F2 未分柜：is_uncategorized 为真', pu['is_uncategorized'] is True)
chk('F3 未分柜：不认领任何报告（files 恒 0）', pu['steps']['report']['files'] == 0)

# ══════════════════════════════════════════════════════════════════
# G 待确认数：只数本柜清单里、未确认的产品
# ══════════════════════════════════════════════════════════════════
codes = [r[0] for r in con.execute("SELECT code_norm FROM products").fetchall()]
chk('G0 清单里的产品都在产品库', len(codes) >= 2, codes)

# 先全部标成已确认，拿到基线
con.execute("UPDATE products SET review_state='confirmed'")
con.commit()
b0 = prog(c1['id'])['steps']['govern']['review_pending']
chk('G1 全部确认 → 待确认 0', b0 == 0, b0)

# 取消一个的确认 → +1
con.execute("UPDATE products SET review_state='pending' WHERE code_norm=?", (codes[0],))
con.commit()
b1 = prog(c1['id'])['steps']['govern']['review_pending']
chk('G2 取消一个确认 → 待确认 1', b1 == 1, b1)

# 再加一个「不在本柜清单里」的产品，不该被数进来
store.upsert_products(con, [{'code': 'ZZZZ9999999', 'name': '不在这个柜的货'}])
con.execute("UPDATE products SET review_state='pending' WHERE code_norm='ZZZZ9999999'")
con.commit()
b2 = prog(c1['id'])['steps']['govern']['review_pending']
chk('G3 只数本柜清单里的编码（别的产品不算）', b2 == 1, b2)

con.close()
shutil.rmtree(tmp, ignore_errors=True)

print('\n%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
