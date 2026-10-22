# -*- coding: utf-8 -*-
"""2026-10-10 三个修复的回归测试。

F1 照片「已关联/未关联」选项卡：flag 参数此前被后端忽略（只处理了
   cand/newprod），两档都返回全部照片 = 筛选失效。
F2 导入清单的新产品漏记 product_batch（upsert_products 的 continue 在
   关联写入之前）→ 柜号筛产品为 0；附历史库回填。
F3 报告六列格式（Part Number / DESCRIPTION / Package Number / Order Qty /
   Loading Qty / Quantity Check result）清单导入 —— 本就支持，锁住不回退。

跑法：python tools/productlib/tests/fixes_1010.py
"""
import os, sys, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, schema            # noqa: E402
from tools.productlib.routes import photos as rphotos  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402
from openpyxl import Workbook      # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_fix1010_')
db = os.path.join(tmp, 't.db')
store.STANDARD_DIR = os.path.join(tmp, 'standard')
con = store.connect(db)


def chk(name, ok, extra=''):
    print(('[ OK ] ' if ok else '[FAIL] ') + name + (('  ' + str(extra)) if extra else ''))
    if not ok:
        globals()['_FAILED'] = True


def make_img(path, seed=0):
    im = Image.new('RGB', (900, 700), (200, 210, 220))
    d = ImageDraw.Draw(im)
    for i in range(0, 900, 40):
        d.line([(i, 0), (i, 700)], fill=(120 + seed, 130, 140), width=6)
    im.save(path, 'JPEG', quality=90)


# ═══════════════════════════════════════════════════════════════════
# F1 flag='linked' / 'unlinked' 必须真的筛选
# ═══════════════════════════════════════════════════════════════════
rphotos.con = lambda: store.connect(db)   # 路由层直连临时库

cid = store.create_container(con, 'FIXCTN01')['id']
imgdir = os.path.join(tmp, 'photos')
os.makedirs(imgdir)
make_img(os.path.join(imgdir, 'a1.jpg'), seed=0)
make_img(os.path.join(imgdir, 'b1.jpg'), seed=80)
store.add_photos(con, imgdir, batch_name='F1批次', container_id=cid)
pids = [r['id'] for r in con.execute('SELECT id FROM photos ORDER BY file')]
# 2026-10-17 老板规则「只有产品需要关联」：待关联队列只收产品图
# （label/product）。这里模拟治理已完成、两张都识别为标识卡 —— 本测试
# 主旨是 linked/unlinked 两档筛选互斥，与治理无关。
con.execute("UPDATE photos SET photo_kind='label' WHERE id IN (%s)"
            % ','.join('?' * len(pids)), pids)
store.upsert_products(con, [{'code': 'FIXCODE01', 'name': '阀门', 'spec': ''}])
store.link(con, 'FIXCODE01', pids[0], 'manual', created_by='tester')

all_r = rphotos.api_photos()
lk_r = rphotos.api_photos(flag='linked')
ul_r = rphotos.api_photos(flag='unlinked')
chk('F1a 全部=2', all_r['total'] == 2, all_r['total'])
chk('F1b flag=linked 只剩已关联 1 张',
    lk_r['total'] == 1 and lk_r['items'][0]['id'] == pids[0], lk_r['total'])
chk('F1c flag=unlinked 只剩未关联 1 张',
    ul_r['total'] == 1 and ul_r['items'][0]['id'] == pids[1], ul_r['total'])
chk('F1d 两档不相交（此前是完全相同的两张）',
    {i['id'] for i in lk_r['items']}.isdisjoint({i['id'] for i in ul_r['items']}))

# ═══════════════════════════════════════════════════════════════════
# F2+F3 清单导入：新增产品记 product_batch；报告六列格式全落库
# ═══════════════════════════════════════════════════════════════════
con.execute('DELETE FROM links')  # 隔离：不让上面 F1 的关联影响柜号计数
con.commit()

cid2 = store.create_container(con, 'FIXCTN02')['id']
store.upsert_products(con, [{'code': 'EXIST999', 'name': '旧产品', 'spec': ''}])

xlsx = os.path.join(tmp, 'report_fmt.xlsx')
wb = Workbook(); ws = wb.active
ws.append(['Packing list data'])  # 标题行（表头定位要跳过）
ws.append(['Part Number', 'DESCRIPTION', 'Package Number',
           'Order Qty', 'Loading Qty', 'Quantity Check result'])
ws.append(['EXIST999', 'OLD ITEM', 'Cage-M239', '10', '10', 'OK'])
ws.append(['NEW888', 'NEW ITEM', 'Pallet-M56', '4', '', 'PASS'])
ws.append(['TOTAL', '', '', '14', '', ''])   # 小计行不进数据
wb.save(xlsx)

r = store.import_checklist_file(con, xlsx, container_id=cid2)
chk('F2a 导入 parsed=2（TOTAL 行被排除）', r['parsed'] == 2 and not r['errors'], r['parsed'])
items = store.list_products(con, container_no='FIXCTN02', limit=50)
codes = {i['code_norm'] for i in items}
chk('F2b 柜号筛选：新增+已存在都筛得到（此前新增=0）',
    codes == {'EXIST999', 'NEW888'}, codes)

rows = store.checklist_rows_of(con, r['batch_id'])
snap = {x['code_norm']: x for x in rows}
chk('F3a 报告六列：Package Number 落库',
    snap['EXIST999']['package_no'] == 'Cage-M239'
    and snap['NEW888']['package_no'] == 'Pallet-M56')
chk('F3b 报告六列：Order/Loading/Check 三列原样落库',
    snap['EXIST999']['order_qty'] == '10'
    and snap['EXIST999']['loading_qty'] == '10'
    and snap['EXIST999']['check_import'] == 'OK'
    and snap['NEW888']['loading_qty'] is None
    and snap['NEW888']['check_import'] == 'PASS')

# 历史库回填：删掉关联模拟老库 → 直调回填（生产上是 connect 时 _migrate 跑）
con.execute("DELETE FROM product_batch WHERE code_norm='NEW888'")
con.commit()
n0 = con.execute("SELECT COUNT(*) FROM product_batch WHERE code_norm='NEW888'").fetchone()[0]
store._migrate_product_batch_backfill(con)
n1 = con.execute("SELECT COUNT(*) FROM product_batch WHERE code_norm='NEW888'").fetchone()[0]
chk('F2c 历史库回填（checklist_rows → product_batch）',
    n0 == 0 and n1 >= 1, '%d -> %d' % (n0, n1))
items2 = store.list_products(con, container_no='FIXCTN02', limit=50)
chk('F2d 回填后柜号筛选恢复', {i['code_norm'] for i in items2} == {'EXIST999', 'NEW888'})

_failed = globals().get('_FAILED', False)
print('\n%s' % ('ALL PASS' if not _failed else 'HAS FAILURES'))
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if _failed else 0)
