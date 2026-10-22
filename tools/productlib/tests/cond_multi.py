# -*- coding: utf-8 -*-
"""④柜况多选（同格多张）在报告里的排版：**不溢出、不被裁、图尽量大**。

老板 2026-10-22 截图：选了多张的格子图被切断、图注掉出格。
根因：行高 EXACTLY 锁 2.82"，而 3 张 × 1.1" 下限 = 3.65" 超出 → Word 裁掉。
修法：≥3 张改格内 2 列网格 + 行高按内容抬升。

量真实几何：行高 / 每张图显示高 / 每格图数与「同段落并排」情况。
⚠️ 量格内总高必须**按段落取最高**再相加 —— 并排的两张在同一段落里只占一行，
   相加会把 2 列排版误算成溢出（第一版断言就是这么假红的）。
"""
import math
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, report_gen  # noqa: E402
from PIL import Image  # noqa: E402
from docx import Document  # noqa: E402

REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))),
    '9.13 5x40HQ', 'MIEU2012616.xlsx')

tmp = tempfile.mkdtemp(prefix='pl_condmulti_')
DATA = os.path.join(tmp, 'data')
os.makedirs(DATA, exist_ok=True)
con = store.connect(os.path.join(DATA, 'productlib.db'))
FAILS = []


def chk(name, ok, info=''):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (('  -> ' + str(info)) if info else ''))
    if not ok:
        FAILS.append(name)


c1 = store.create_container(con, 'EMCU8800001', client_name='Test')
store.import_checklist_file(con, REAL, container_id=c1['id'])

src = os.path.join(tmp, '交付')
sd = os.path.join(src, '监装')
os.makedirs(sd)
# 8 张：empty=3, side=3, seal=2, lock=1
plan = [('empty_container', 3), ('container_side', 3),
        ('container_seal', 2), ('container_lock', 1)]
n = 0
for tag, cnt in plan:
    for _ in range(cnt):
        n += 1
        # 竖图（更容易看出被裁）与横图混合
        w, h = (900, 1600) if n % 2 else (1600, 1200)
        Image.new('RGB', (w, h), (30 * n % 255, 80, 160)).save(
            os.path.join(sd, 'S_%02d.jpg' % n))

ap = store.add_photos(con, src, container_id=c1['id'])
pids = [r['id'] for r in con.execute(
    'SELECT id FROM photos ORDER BY file')]
for pid in pids:
    store.set_photo_usage(con, pid, '监装')
i = 0
cond_picks = {}
for tag, cnt in plan:
    store.set_supervision_tag(con, pids[i:i + cnt], tag)
    cond_picks[tag] = pids[i:i + cnt]      # 多张只能走 picks 指定（自动只取 1 张）
    i += cnt

data = store.loading_report_data(con, c1['id'],
                                 picks={'conds': cond_picks})
cond = data.get('conditions') or {}
print('  conditions 张数:', {k: len(v) for k, v in cond.items()})

out = os.path.join(tmp, 'r.docx')
r = report_gen.build_loading_report(data, out, photo_root=DATA)
print('  生成:', os.path.basename(r['path']), '| 图片', r['photos'])

# ── 量几何 ────────────────────────────────────────────────
doc = Document(out)
print('  表格:', [(len(tb.rows), len(tb.columns)) for tb in doc.tables])
t = None
for tb in doc.tables:
    if len(tb.rows) == 2 and len(tb.columns) == 2:
        t = tb
        break
chk('找到 2×2 柜况表', t is not None)

NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
EMU = 914400.0

# 直接从 document.xml 读所有 trHeight（python-docx 的 row.height 读不到时靠它）
with zipfile.ZipFile(out) as z:
    xml = z.read('word/document.xml').decode('utf8')
import re as _re
trh = [int(v) / 1440.0 for v in _re.findall(r'<w:trHeight[^>]*w:val="(\d+)"', xml)]
print('  文档内所有 trHeight(inch):', [round(x, 2) for x in trh])
print('  Not provided 次数:', xml.count('Not provided'),
      '| Photo error 次数:', xml.count('Photo error'))


def tr_h(row):
    # ⚠️ trHeight 在 <w:trPr> 下面，不是 tr 的直接子元素 —— 必须用 .// 搜
    e = row._tr.find('.//' + NS + 'trHeight')
    return int(e.get(NS + 'val')) / 1440.0 if e is not None else None


def cell_stats(cell):
    """返回 (图数, 每张显示高, 每段图数, 每段最高)。

    并排的两张在**同一段落**里 → 视觉上只占一行，量总高必须按「每段取最高」，
    不能把同段两张的高度相加（否则 2 列排版本会被算成溢出）。"""
    heights, per_para, para_h = [], [], []
    for p in cell.paragraphs:
        hh = []
        for run in p.runs:
            for ext in run._r.iter(
                    '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent'):
                hh.append(int(ext.get('cy')) / EMU)
        if hh:
            heights.extend(hh)
            per_para.append(len(hh))
            para_h.append(max(hh))
    return len(heights), heights, per_para, para_h


rows_h = [tr_h(row) for row in t.rows]
print('  行高(inch):', [round(x, 3) if x else x for x in rows_h])
chk('两行都有行高且 ≥ 2.82"（不低于原预算）',
    all(x and x >= 2.80 for x in rows_h), rows_h)

tags = ('empty_container', 'container_side', 'container_seal', 'container_lock')
total_imgs = 0
for idx, tag in enumerate(tags):
    cell = t.rows[idx // 2].cells[idx % 2]
    cnt, hs, pp, ph = cell_stats(cell)
    total_imgs += cnt
    want = dict(plan)[tag]
    row_i = idx // 2
    used = sum(ph) + report_gen.COND_CAPTION_H_IN   # 每段一行（并排算一行）
    fits = used <= rows_h[row_i] + 0.01
    chk('%s：%d 张全部嵌入' % (tag, want), cnt == want, '%d/%d' % (cnt, want))
    chk('%s：格内总高 %.2f" ≤ 行高 %.2f"（不被裁）'
        % (tag, used, rows_h[row_i]), fits, 'heights=%s' % [round(x, 3) for x in hs])
    if want >= 3:
        chk('%s：≥3 张走 2 列（同段落并排）' % tag,
            pp and max(pp) >= 2, 'per_para=%s' % pp)

with zipfile.ZipFile(out) as z:
    media = len([n for n in z.namelist() if n.startswith('word/media/')])
print('  实际嵌入 media 数:', media)
chk('柜况 9 张全部嵌入（media 数 ≥ 9）', media >= 9, media)

print('----')
print('FAIL %d' % len(FAILS))
if FAILS:
    for f in FAILS:
        print('  -', f)
    sys.exit(1)
