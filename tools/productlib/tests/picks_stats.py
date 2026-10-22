# -*- coding: utf-8 -*-
"""④选图「柜级统计」的口径回归（2026-10-10）。

统计条是给老板看「还差多少」的：总数、命中、缺口、占比，外加照片维度
（本柜导入的照片里命中多少张、其中标准图多少张）。

🔴 锁的重点不是数字本身，而是**它与检索列表同源**（铁律 23）：
   「命中 N」必须等于 /api/report/lookup 结果里 found=True 的条数。
   两边各写一份判定必然漂移 —— 所以这里直接跑 report_lookup 对比。

场景（CTN1）：
  A  产品库有 + 有照片          → 命中
  B  产品库有 + 无照片          → 缺口
  C  产品库没有（新产品未确认） → 缺口
照片：3 张非副本 + 1 张副本（副本关联 A，但不许计入命中）
标准图：其中 1 张做了标准图

跑法：python tools/productlib/tests/picks_stats.py
"""
import os, sys, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store                 # noqa: E402
from PIL import Image                              # noqa: E402
from openpyxl import Workbook                      # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_picks_')
db = os.path.join(tmp, 't.db')
store.STANDARD_DIR = os.path.join(tmp, 'standard')
con = store.connect(db)

_FAILED = False


def chk(name, ok, extra=''):
    global _FAILED
    print(('[ OK ] ' if ok else '[FAIL] ') + name + (('  ' + str(extra)) if extra else ''))
    if not ok:
        _FAILED = True


def jpg(path, seed):
    Image.new('RGB', (800, 600), (seed, 120, 160)).save(path, 'JPEG', quality=88)


# ── 建柜 + 导入清单（A / B / C 三个编码）──
cid = store.create_container(con, 'CTN1')['id']
wb = Workbook(); ws = wb.active
ws.append(['Part Number', 'DESCRIPTION', 'Package Number', 'Order Qty'])
ws.append(['A100', '产品A', 'PKG-1', '10'])
ws.append(['B200', '产品B', 'PKG-2', '5'])
ws.append(['C300', '产品C', 'PKG-3', '7'])
xlsx = os.path.join(tmp, 'list.xlsx'); wb.save(xlsx)
store.import_checklist_file(con, xlsx, container_id=cid)

# 导入清单本身会把三个编码都建成产品（upsert_products），所以这里**删掉 C**
# 来还原真实场景里的「清单里有、产品库还没确认这个编码」。
store.upsert_products(con, [{'code': 'A100', 'name': '产品A', 'spec': ''},
                            {'code': 'B200', 'name': '产品B', 'spec': ''}])
con.execute("DELETE FROM products WHERE code_norm='C300'")
con.commit()

# ── 本柜照片批次：4 张（最后一张手工标成副本）──
phdir = os.path.join(tmp, 'photos'); os.makedirs(phdir, exist_ok=True)
files = []
for i, seed in enumerate((10, 40, 70, 100)):
    p = os.path.join(phdir, 'ph%d.jpg' % i)
    jpg(p, seed)
    files.append(p)
store.add_photos(con, phdir, container_id=cid)
phs = con.execute('SELECT id, file FROM photos ORDER BY file').fetchall()
# photos.file 只存文件名（add_photos 不落全路径），按 basename 索引
by_name = {os.path.basename(r['file']): r for r in phs}
p_a = by_name['ph0.jpg']['id']
p_dup = by_name['ph3.jpg']['id']
con.execute('UPDATE photos SET is_dup=1 WHERE id=?', (p_dup,))
con.commit()

# A 关联一张真图 + 一张副本（副本不该让命中数虚高）
store.link(con, 'A100', p_a, 'manual', confidence=0.9, evidence='test', created_by='t')
store.link(con, 'A100', p_dup, 'manual', confidence=0.9, evidence='test', created_by='t')

# 标准图：给 p_a 做一张（标准图走 code_norm 文件夹布局）
with open(files[0], 'rb') as f:
    store.add_standard_image(con, 'A100', p_a, 'product', f.read(), by='t')

# ═══════════════════════════════════════════════════════════════════
st = store.container_picks_stats(con, cid)
print('stats =', st)

chk('清单编码总数 = 3', st['codes_total'] == 3, st['codes_total'])
chk('产品库已有 = 2（C 不在库）', st['in_lib'] == 2, st['in_lib'])
chk('命中（有照片）= 1（只有 A）', st['with_photo'] == 1, st['with_photo'])
chk('缺口 = 2（B 无图 + C 无此编码）', st['missing'] == 2, st['missing'])
chk('命中占比 = 33.3%', abs(st['hit_rate'] - 33.3) < 0.1, st['hit_rate'])
chk('本柜照片 = 3 张（副本不算）', st['photo_total'] == 3, st['photo_total'])
chk('已关联（命中照片）= 1（副本链接不算）', st['photo_linked'] == 1, st['photo_linked'])
chk('标准图 = 1 张', st['std_photos'] == 1, st['std_photos'])

# ── 同源性：统计的「命中」必须等于检索结果的 found 数 ──
res = store.report_lookup(con, ['A100', 'B200', 'C300'], container_id=cid)
found = [r for r in res if r.get('found')]
chk('report_lookup 命中数 == 统计 with_photo',
    len(found) == st['with_photo'], '%d vs %d' % (len(found), st['with_photo']))
chk('report_lookup 总数 == 清单编码数', len(res) == st['codes_total'],
    '%d vs %d' % (len(res), st['codes_total']))

# ── 挂在 progress 上（前端只认这一个入口）──
prog = store.container_progress(con, cid)
chk('progress.steps.picks.stats 存在', bool(prog['steps'].get('picks', {}).get('stats')))
chk('progress 里的统计与直调一致', prog['steps']['picks']['stats']['with_photo'] == 1)

# ── 空柜（无清单）不该炸，全 0 ──
cid2 = store.create_container(con, 'CTN2')['id']
st2 = store.container_picks_stats(con, cid2)
chk('空柜统计全 0 且不抛', st2['codes_total'] == 0 and st2['hit_rate'] == 0.0, st2)

print()
print('FAIL' if _FAILED else 'ALL PASS')
con.close()
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if _FAILED else 0)
