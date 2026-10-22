# -*- coding: utf-8 -*-
"""标签区域裁剪（2026-10-17 老板需求）：det 框 → 聚区域 → 裁剪二次 OCR + 视觉。

锁死四件事：
  1. label_region 纯函数：正常标签区/占比过大/过小/无框 四种判定；
  2. run_photo 新格式：texts 每项带 box（原图坐标）；
  3. 端到端：PIL 画「白底黑字编码标签」贴大图一角 → OCR 检出框 →
     聚出区域 → 裁剪图二次 OCR 读出画上去的码；
  4. 裁剪增强失败绝不挡治理（异常路径静默返回原 texts）。

注意：真实跑 PaddleOCR（本地 onnx）。纯色渐变图 det 无框是正常现象，
所以画字时用足够大的字号。
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import pipeline, store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pc_ocr_probe as P  # noqa: E402

FAILS = []


def chk(name, cond, extra=''):
    tag = '[ OK ]' if cond else '[FAIL]'
    print('%s %s %s' % (tag, name, extra))
    if not cond:
        FAILS.append(name)


tmp = tempfile.mkdtemp(prefix='pl_label_')

# ── 1. label_region 纯函数 ──────────────────────────────────────
W, H = 3000, 4000
r = pipeline.label_region([[100, 200, 800, 400]], W, H)
chk('1a 单框 + 12% 边距', r is not None and
    abs(r[0] - (100 - 84)) <= 1 and abs(r[1] - (200 - 24)) <= 1, r)
chk('1b 单框判定成立（面积占 2.6% < 45%）', r is not None, r)
r2 = pipeline.label_region([[0, 0, 2900, 3900]], W, H)      # 占比 94%
chk('1c 占比过大 → None（文字满图不裁）', r2 is None, r2)
r3 = pipeline.label_region([[10, 10, 80, 60]], W, H)        # 70×50 < 160px
chk('1d 区域过小 → None', r3 is None, r3)
chk('1e 无框 → None', pipeline.label_region([], W, H) is None)
chk('1f 框越界被 clamp', pipeline.label_region(
    [[-50, -50, W + 50, 300]], W, H) is not None)

# ── 2/3. 真图端到端：画标签 → OCR 检框 → 聚区域 → 裁剪再读 ────────
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
CODE = '103011013388A'


def make_label_photo(path):
    """大图（3000×4000）左上角贴一张白底黑字标签（编码大字）。"""
    im = Image.new('RGB', (W, H), (150, 160, 170))
    d = ImageDraw.Draw(im)
    # 标签底板：白底黑框，占左上角一块（约 1200×420 —— 面积 4% < 45%）
    d.rectangle([80, 120, 1280, 540], fill=(255, 255, 255), outline=(0, 0, 0), width=6)
    f = None
    for size in (110, 90, 72, 56, 44):
        try:
            f = ImageFont.truetype('arial.ttf', size)
            break
        except OSError:
            continue
    if f is None:
        f = ImageFont.load_default()
    d.text((110, 200), CODE, fill=(10, 10, 10), font=f)
    d.text((110, 380), 'VALVE DN50', fill=(30, 30, 30), font=f)
    im.save(path, 'JPEG', quality=92)


photo_path = os.path.join(tmp, 'label.jpg')
make_label_photo(photo_path)

r1 = P.run_photo(photo_path)
box_n = r1.get('boxes', 0)
chk('2 整图 OCR 检出文本框', box_n > 0, 'boxes=%s texts=%d' % (box_n, len(r1['texts'])))
chk('2b texts 新格式带 box（原图坐标）',
    all(isinstance(t.get('box'), list) and len(t['box']) == 4
        for t in r1['texts']), r1['texts'][:2])
whole_codes = ' '.join(t['t'] for t in r1['texts'])
chk('2c 整图能读出编码（PIL 画的印刷体，PP-OCR 应能读）',
    CODE[:6] in whole_codes.replace(' ', ''), whole_codes[:80])

reg = pipeline.label_region([t['box'] for t in r1['texts']], W, H)
chk('3 det 框聚出标签区域', reg is not None, reg)
if reg:
    from PIL import Image  # noqa: E811
    im = Image.open(photo_path)
    crop = im.crop(reg)
    scale = max(1.0, 1280.0 / min(crop.size))
    crop = crop.resize((int(crop.size[0] * scale), int(crop.size[1] * scale)),
                       Image.LANCZOS)
    cp = os.path.join(tmp, 'crop.jpg')
    crop.save(cp, 'JPEG', quality=90)
    r2 = P.run_photo(cp)
    crop_codes = ' '.join(t['t'] for t in r2['texts'])
    chk('3b 裁剪放大图读出完整编码', CODE in crop_codes.replace(' ', ''),
        crop_codes[:80])
    chk('3c 裁剪区域明显小于整图', (reg[2] - reg[0]) * (reg[3] - reg[1])
        < W * H * pipeline.LABEL_REGION_MAX_AREA, reg)

# ── 4. 增强失败不挡治理：构造坏 boxes 走 _label_crop_ocr ────────────
con = store.connect(os.path.join(tmp, 't.db'))
_c = store.create_container(con, 'LBL0000001')
n = store.add_photos(con, tmp, batch_name='标签批次', container_id=_c['id'],
                     file_filter=lambda f: f.endswith('label.jpg')) \
    if 'file_filter' in store.add_photos.__code__.co_varnames else \
    store.add_photos(con, tmp, batch_name='标签批次', container_id=_c['id'])
pid = con.execute('SELECT id FROM photos LIMIT 1').fetchone()['id']
bad_texts = [{'t': 'GARBAGE', 'c': 0.9, 'box': 'not-a-list'}]
m2, crop2 = pipeline._label_crop_ocr(con, {'id': pid, 'path': photo_path},
                                     bad_texts, 'label')
chk('4 坏框数据静默降级（返回原 texts）', m2 == bad_texts and crop2 is None)

shutil.rmtree(tmp, ignore_errors=True)
print('----')
if FAILS:
    print('FAIL:', ' / '.join(FAILS))
    sys.exit(1)
print('ALL_PASS')
