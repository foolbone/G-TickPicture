# -*- coding: utf-8 -*-
"""报告分页：每页 6 张图 + 章节从新页开始（2026-10-07 老板需求）。

为什么单独一个文件：loading_report.py 的 fixture 只有 2 张核对照，
分不出「每页 6 张」和「不分页」—— 断言在那种数据下**恒绿**，等于没查
（铁律 12：别信「0 项检查」的绿，新检查必须用探针证明它真会红）。

这里直接喂 14 张核对照 + 7 张卡车照，把 document.xml 拆开数：
  · 每张表的嵌图数 → 有没有哪页超过 6 张
  · <w:br w:type="page"> 的个数 → 章节分页 + 照片切页各几个

不依赖数据库，只喂 build_loading_report 的数据结构（生成器是纯函数）。
"""
import os
import sys
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from tools.productlib import report_gen  # noqa: E402

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'

FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


tmp = tempfile.mkdtemp(prefix='pl_page_')


def mk(name, w, h, color):
    from PIL import Image
    p = os.path.join(tmp, name)
    Image.new('RGB', (w, h), color).save(p)
    return p


# ── 数据：14 张核对照 + 7 张卡车 + 4 张柜况 ──────────────────────
N_CHECK, N_TRUCK = 14, 7
# ⚠️ 每张图的**像素必须不同**：python-docx 按图片字节 sha1 复用 image part，
#    14 张一模一样的图在 word/media/ 里只落 1 个文件（不是 14 个）——
#    数 media 文件个数前先保证内容互异，否则会误判「图少了」。
checks = [{'path': mk('c%02d.jpg' % i, 1600, 1200, (200, 30 + i * 4, 30)),
           'caption': [{'text': 'Part No. 213050000%03d' % i, 'size': 8,
                        'bold': True},
                       {'text': 'Hose ROCKMASTER %d' % i, 'size': 7.5},
                       {'text': 'Package: Cage-M%04d' % i, 'size': 7}]}
          for i in range(N_CHECK)]
trucks = [{'path': mk('t%02d.jpg' % i, 1400, 900, (200, 200, 10 + i * 6)), 'tag': 'other'}
          for i in range(N_TRUCK)]
cond = {tag: mk('s%d.jpg' % i, 1200, 900, (40 * i, 60, 200))
        for i, tag in enumerate(('empty_container', 'container_side',
                                 'container_seal', 'container_lock'))}
data = {
    'meta': {'container_no': 'EMCU9914616', 'seal_no': 'EMCEXE7565',
             'inspector': 'Jerry Xu', 'client_name': 'ACME',
             'product_name': 'ACCESSORIES', 'inspection_date': '2026-09-27',
             'location': 'Changsha', 'arrival_at': '8:49', 'departure_at': '11:27',
             'remark': 'PASS'},
    'summary': {'order_total': 100, 'order_qty_display': 100,
                'loading_qty_display': 100},
    'rows': [{'code': '213050000001', 'name': 'Hose', 'package_no': 'Cage-M0001',
              'order_qty': '50', 'loading_qty': '50', 'check': 'OK'}],
    'checks': checks,
    'trucks': trucks,
    'conditions': cond,
}

out = os.path.join(tmp, 'page.docx')
r = report_gen.build_loading_report(data, out)
chk('P1 docx 生成成功', os.path.exists(out) and r['bytes'] > 10000, r['bytes'])

with zipfile.ZipFile(out) as z:
    xml = z.read('word/document.xml').decode('utf8')
    n_media = len([n for n in z.namelist() if n.startswith('word/media/')])
root = ET.fromstring(xml)
tbls = list(root.iter(W + 'tbl'))
counts = [len(list(t.iter(A + 'blip'))) for t in tbls]
breaks = [e for e in root.iter(W + 'br') if e.get(W + 'type') == 'page']

chk('P2 嵌图总数 = 4柜况 + 14核对 + 7卡车',
    n_media == 4 + N_CHECK + N_TRUCK, n_media)

# 表顺序：②项目信息 / ③柜汇总 / ④信息表 / ④柜况2×2 / ⑤清单 / ⑥… / ⑦…
grid = [c for c in counts if c > 0]
chk('P3 每张照片表都不超过 6 张（一页 6 张的硬约束）',
    max(grid) <= 6, '各表嵌图数 %s' % grid)
chk('P4 ⑥ 14 张切成 3 页（6 / 6 / 2）',
    counts[-4:] == [6, 6, 2, 6] or grid[-5:] == [6, 6, 2, 6, 1],
    '尾部各表 %s' % grid[-5:])
chk('P5 ⑦ 7 张切成 2 页（6 / 1）', grid[-2:] == [6, 1], '尾部 %s' % grid[-2:])
chk('P6 ④ 柜况 2×2 仍是单表 4 张（≤6，不切）', counts[3] == 4, counts[3])

# 分页符：④⑤⑥⑦ 四个章节各 1 个 + ⑥ 切页 2 个 + ⑦ 切页 1 个
exp_breaks = 4 + (3 - 1) + (2 - 1)
chk('P7 分页符数 = 4 章节 + ⑥切页2 + ⑦切页1 = %d' % exp_breaks,
    len(breaks) == exp_breaks, len(breaks))

chk('P8 每页 6 张的常量就是 6（需求口径，别被改掉）',
    report_gen.PHOTOS_PER_PAGE == 6, report_gen.PHOTOS_PER_PAGE)
chk('P9 每页 3 行（2 列 × 3 = 6）',
    report_gen.GRID_COLS * report_gen.GRID_ROWS_PER_PAGE == 6,
    '%d x %d' % (report_gen.GRID_COLS, report_gen.GRID_ROWS_PER_PAGE))
chk('P10 版心装得下「标题 + 3 行照片」（装不下会静默掉成 4 张/页）',
    report_gen.page_budget_ok(),
    '标题 %.2f + 3x%.2f = %.2f / 版心 %.2f'
    % (report_gen.SECTION_TITLE_H_IN, report_gen.PHOTO_ROW_H_IN,
       report_gen.SECTION_TITLE_H_IN + 3 * report_gen.PHOTO_ROW_H_IN,
       report_gen.CONTENT_H_IN))

# ── P14 纸型必须是 A4（2026-10-11 真实报告事故）──────────────────
# python-docx 默认模板是 Letter（8.5×11"）。以前 build_loading_report 只设
# 页边距不设纸型，版心高只有 9.0"，第三行照片被顶到下一页 = 每页 4 张，
# 而 page_budget_ok 按 A4 算恒绿 —— 只有查生成产物的 pgSz 才抓得到。
from docx import Document as _Doc  # noqa: E402
_sec = _Doc(out).sections[0]
_w, _h = _sec.page_width.inches, _sec.page_height.inches
chk('P14 纸型 = A4（Letter 会让版心只剩 9.0"、每页静默掉成 4 张）',
    abs(_w - report_gen.PAGE_W_IN) < 0.01 and abs(_h - report_gen.PAGE_H_IN) < 0.01,
    '实际 %.2f x %.2f' % (_w, _h))

# ── 对照组：证明上面这批断言**真会红**（不分页时应该是 1 张长表）──
from docx import Document  # noqa: E402
d2 = Document()
n2 = report_gen._grid_photos(d2, checks, lambda it: it.get('caption'),
                             'Not provided', per_page=len(checks))
o2 = os.path.join(tmp, 'ctl.docx')
d2.save(o2)
with zipfile.ZipFile(o2) as z:
    root2 = ET.fromstring(z.read('word/document.xml').decode('utf8'))
tbls2 = list(root2.iter(W + 'tbl'))
chk('P11 对照组：不切页时就是 1 张表 14 张图（计数方法确实能分辨）',
    len(tbls2) == 1 and len(list(tbls2[0].iter(A + 'blip'))) == N_CHECK,
    '%d 张表 / %d 张图' % (len(tbls2),
                           len(list(tbls2[0].iter(A + 'blip'))) if tbls2 else 0))
chk('P12 对照组：不切页时无分页符（P7 的 7 个不是凭空来的）',
    len([e for e in root2.iter(W + 'br') if e.get(W + 'type') == 'page']) == 0)
chk('P13 每组都返回了实际嵌入张数', n2 == N_CHECK, n2)

# ── 断层回归（2026-10-18 老板实测：一页 2 张、一页 5 张）────────────
# 根因：真实品名 40~60 字符、一个编码分装多箱时箱号 join 5+ 个 —— 图注
# 从 3 行涨到 6+ 行，行高撑爆 PHOTO_ROW_H_IN 的 0.62" 预算，Word 把
# 整行挤到下页。断言：caption 生成器对超长输入**限长/收起**。
cap_long = report_gen._caption_check({
    'code': '1050604012B4C1',
    'name': 'Disconnect ECU power 2 minutes after shutdown only for safety',
    'cartons': ['Cage-M013', 'Cage-M028', 'Cage-M020', 'Cage-M117',
                'Cage-M228', 'Cage-M331'],
    'carton': 'Cage-M013 / Cage-M028 / Cage-M020 / Cage-M117 / Cage-M228 / Cage-M331'})
chk('P14 超长品名被截断（≤ CAP_NAME_MAX）',
    all(len(l['text']) <= report_gen.CAP_NAME_MAX for l in cap_long[1:2]),
    [l['text'] for l in cap_long][1:2])
chk('P15 品名行带省略号（不是硬切）', cap_long[1]['text'].endswith('…'),
    cap_long[1]['text'][-3:])
chk('P16 多箱号收起为「前 2 个 + N more」',
    cap_long[2]['text'] == 'Package: Cage-M013 / Cage-M028  +4 more',
    cap_long[2]['text'])
chk('P17 caption 恒为 3 段（件号/描述/箱号，行高预算的前提）',
    len(cap_long) == 3, len(cap_long))
chk('P18 版心仍装得下「标题 + 3 行照片」', report_gen.page_budget_ok())
# 旧字段 carton（str）兜底不炸
cap_old = report_gen._caption_check({'code': 'X', 'carton': 'Cage-M001'})
chk('P19 旧格式 carton 字符串兜底', cap_old[-1]['text'] == 'Package: Cage-M001',
    cap_old[-1]['text'])

shutil.rmtree(tmp, ignore_errors=True)
print('\n%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
