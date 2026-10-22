# -*- coding: utf-8 -*-
"""G1~G5 临时库单测：pHash / 近标准图 / 压缩 / picks / report.html / has_standard。"""
import os, sys, csv, shutil, tempfile, io, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, schema  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_g_')
db = os.path.join(tmp, 't.db')
store.STANDARD_DIR = os.path.join(tmp, 'standard')   # 防污染真实标准图目录


def make_img(path, size=(1200, 900), seed=0):
    """带渐变+条纹的图（纯色图 DCT 无区分度，pHash 会不稳）。"""
    im = Image.new('RGB', size, (200, 210, 220))
    d = ImageDraw.Draw(im)
    for i in range(0, size[0], 40):
        d.line([(i, 0), (i, size[1])], fill=(120, 130, 140), width=6)
    base = 80 if seed == 0 else 160
    for j in range(0, size[1], 60):
        d.rectangle([0, j, size[0], j + 20], fill=(60, base, base + 50))
    d.ellipse([size[0]*0.3, size[1]*0.3, size[0]*0.7, size[1]*0.7],
              fill=(220 - seed*80, 90, 60))
    im.save(path, 'JPEG', quality=90)


imgdir = os.path.join(tmp, 'photos')
os.makedirs(imgdir)
make_img(os.path.join(imgdir, 'a1.jpg'), (1200, 900), seed=0)
make_img(os.path.join(imgdir, 'b1.jpg'), (900, 1200), seed=1)

con = store.connect(db)

# v3：无柜不导 —— 导入必须先建柜（闸门在后端）
_c = store.create_container(con, 'TEST0000001')
n = store.add_photos(con, imgdir, batch_name='测试批次', container_id=_c['id'])
assert n['added'] == 2 and n['batch_id'], n
store.upsert_products(con, [{'code': '103011013388A', 'name': '阀门A', 'spec': 'DN50'}])
rows = con.execute('SELECT id, file FROM photos ORDER BY file').fetchall()
pid1 = next(r['id'] for r in rows if r['file'].endswith('a1.jpg'))
pid2 = next(r['id'] for r in rows if r['file'].endswith('b1.jpg'))
store.link(con, '103011013388A', pid1, 'manual', created_by='tester')
store.link(con, '103011013388A', pid2, 'manual', created_by='tester')

# -- G3 pHash ------------------------------------------------------
h1a = store._phash(os.path.join(imgdir, 'a1.jpg'))
h1b = store._phash(os.path.join(imgdir, 'a1.jpg'))
h2 = store._phash(os.path.join(imgdir, 'b1.jpg'))
assert h1a is not None and h1a == h1b, '同图哈希应稳定相等'
assert store._phash_dist(h1a, h2) > 0, '不同图距离应 > 0'
print('[ OK ] phash: same-image dist=0, diff-image dist=%d' % store._phash_dist(h1a, h2))

# -- 标准图（用 a1 做标准图 → a1 应是最像参考图的） -----------------
with open(os.path.join(imgdir, 'a1.jpg'), 'rb') as f:
    sid = store.add_standard_image(con, '103011013388A', pid1, 'product', f.read())
assert store.standard_ref(con, '103011013388A'), 'standard_ref 应返回路径'
print('[ OK ] standard_ref: %s' % os.path.basename(store.standard_ref(con, '103011013388A')))

# -- G3 lookup 近标准图标签 + reasons ------------------------------
res = store.report_lookup(con, ['103011013388a'])     # 故意小写输入，验证归一化
it = res[0]
assert it['found'] and it['photo_count'] == 2, it
near = [p for p in it['photos'] if '近标准图' in p['tags']]
assert len(near) == 1 and near[0]['photo_id'] == pid1, 'a1 应唯一命中近标准图'
assert any('与标准参考图最接近' in r for r in near[0]['reasons']), near[0]['reasons']
assert all(p['reasons'] for p in it['photos']), '每张候选都应有理由文案'
assert it['photos'][0]['recommended'] and it['photos'][0]['photo_id'] == pid1
print('[ OK ] lookup: near-standard tag on a1, reasons present, top1=a1')

# -- G2 压缩 + G4 picks + G5 report.html ---------------------------
outd = os.path.join(tmp, 'out')
r = store.report_export(con, outd, ['103011013388a', '999999999999Z'],
                        long_edge=400, picks={'103011013388A': pid2})
assert r['matched'] == 1 and r['missing'] == 1, r
subs = [x for x in sorted(os.listdir(outd)) if os.path.isdir(os.path.join(outd, x))]
assert len(subs) == 1, subs
files = os.listdir(os.path.join(outd, subs[0]))
assert len(files) == 1, files
fp = os.path.join(outd, subs[0], files[0])
with Image.open(fp) as im:
    w, h = im.size
assert max(w, h) <= 400, (w, h)
assert os.path.getsize(fp) < os.path.getsize(os.path.join(imgdir, 'a1.jpg')), '压缩后应更小'
print('[ OK ] export long_edge=400: %dx%d, %d bytes (smaller than source)' % (w, h, os.path.getsize(fp)))

# picks 指定的是 b1(pid2)，CSV 状态必须是「人工指定」而非「采用」
with open(os.path.join(outd, 'report_index.csv'), encoding='utf-8-sig') as f:
    crows = list(csv.reader(f))
data_rows = [x for x in crows[1:] if x[4] != '缺口']
assert len(data_rows) == 1 and data_rows[0][4] == '人工指定', data_rows
assert data_rows[0][9] == '%dx%d' % (w, h), data_rows[0][9]
gap_rows = [x for x in crows[1:] if x[4] == '缺口']
assert len(gap_rows) == 1 and gap_rows[0][10] == '库内无此编码', gap_rows
print('[ OK ] export picks: CSV state=人工指定, gap row with reason')

# G5 report.html：存在、内嵌 base64 图、含缺口表
html = open(os.path.join(outd, 'report.html'), encoding='utf-8').read()
assert 'data:image/jpeg;base64,' in html, '报告应内嵌缩略图'
assert '缺口' in html and '999999999999Z' in html, '报告应含缺口表'
assert '103011013388A' in html
assert r['report_html'] == os.path.join(outd, 'report.html')
print('[ OK ] report.html: embedded images + gap table (%d chars)' % len(html))

# 全部导出模式 + 无 picks 回归（取 recommended）
outd2 = os.path.join(tmp, 'out2')
r2 = store.report_export(con, outd2, ['103011013388a'], all_photos=True, long_edge=0)
assert r2['files'] == 2, r2
print('[ OK ] export all_photos+原图: 2 files')

# -- G1 list_products.has_standard --------------------------------
prods = store.list_products(con)
assert prods[0]['has_standard'] == 1, prods[0]['code']
con2 = store.connect(os.path.join(tmp, 'empty.db'))
store.upsert_products(con2, [{'code': '103099999999X', 'name': 'x', 'spec': ''}])
assert store.list_products(con2)[0]['has_standard'] == 0
print('[ OK ] list_products.has_standard: 1 with / 0 without')

con.close(); con2.close()
shutil.rmtree(tmp, ignore_errors=True)
print('ALL_PASS')
