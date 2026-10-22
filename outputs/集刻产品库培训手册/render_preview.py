# -*- coding: utf-8 -*-
"""把生成好的 .pptx **读回来**渲染成 PNG，用于人眼/自动检查版式。

⚠️ 为什么必须回读渲染，而不是「我写的时候算得对就行」：
   python-pptx 只是把坐标写进 XML，没有任何布局校验 ——
   文字超出框、图片压到页脚、相邻两块重叠，它一律不报错，
   打开时才炸。所以要**从文件里把形状读出来**按真实坐标重画一遍，
   看到的就是用户会看到的东西（字号/换行是近似，但溢出与重叠能看准）。
"""
import os
import sys
from pptx import Presentation
from pptx.util import Emu
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
PPTX = os.path.join(BASE, '集刻产品库培训手册.pptx')
OUT = os.path.join(BASE, 'preview')
os.makedirs(OUT, exist_ok=True)

CJK = None
for c in (r'C:\Windows\Fonts\msyh.ttc', r'C:\Windows\Fonts\simhei.ttf'):
    if os.path.exists(c):
        CJK = c
        break
_fc = {}


def font(px_size, bold=False):
    key = (int(px_size), bold)
    if key not in _fc:
        try:
            f = ImageFont.truetype(CJK, int(px_size),
                                   index=1 if bold and CJK.endswith('ttc') else 0)
        except Exception:
            f = ImageFont.truetype(CJK, int(px_size))
        _fc[key] = f
    return _fc[key]


def E(v):
    return v / 914400.0 * 96.0 if v is not None else 0.0


def wrap(draw, text, fnt, maxw):
    """按像素宽度折行（CJK 按 1em、ASCII 按 0.55em 估算）。"""
    lines, cur = [], ''
    for ch in text:
        if ch == '\n':
            lines.append(cur); cur = ''; continue
        w = draw.textlength(cur + ch, font=fnt)
        if w > maxw and cur:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def render(idx, slide, sw, sh):
    img = Image.new('RGB', (int(sw), int(sh)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    overflow = []
    for shp in slide.shapes:
        x, y = E(shp.left), E(shp.top)
        w, h = E(shp.width), E(shp.height)
        # 越界检测（允许 1px 误差）
        if x < -1 or y < -1 or x + w > sw + 1 or y + h > sh + 1:
            overflow.append((shp.shape_type, round(x), round(y),
                             round(w), round(h)))
        # 图片
        if shp.shape_type == 13 or shp.__class__.__name__ == 'Picture':
            try:
                import io as _io
                im = Image.open(_io.BytesIO(shp.image.blob)).convert('RGB')
                # 保持比例：形状给的 w/h 已是按比例算好的，这里再保一次，
                # 免得渲染出拉伸的样子误判成版式问题
                sc = min(w / im.size[0], h / im.size[1])
                nw, nh = max(1, int(im.size[0] * sc)), max(1, int(im.size[1] * sc))
                im = im.resize((nw, nh))
                img.paste(im, (int(x + (w - nw) / 2), int(y + (h - nh) / 2)))
            except Exception:
                d.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=2)
            continue
        # 形状底色
        fill = None
        try:
            if shp.fill.type is not None and shp.fill.type == 1:
                fill = tuple(shp.fill.fore_color.rgb)
        except Exception:
            pass
        line = None
        try:
            if shp.line.fill.type == 1:
                line = tuple(shp.line.color.rgb)
        except Exception:
            pass
        if fill or line:
            d.rounded_rectangle([x, y, x + w, y + h], radius=6,
                                fill=fill, outline=line)
        # 文字
        if not shp.has_text_frame:
            continue
        cy = y + 4
        for para in shp.text_frame.paragraphs:
            runs = [r for r in para.runs if r.text]
            if not runs:
                cy += 6
                continue
            size = 17
            bold = False
            color = (30, 30, 30)
            try:
                size = runs[0].font.size.pt if runs[0].font.size else 17
                bold = bool(runs[0].font.bold)
                color = tuple(runs[0].font.color.rgb)
            except Exception:
                pass
            # 🔴 把整段拆成「字符流」再按像素宽度折行 —— 逐 run 各自折行
            #    会在 run 边界处漏折，整行冲出框外，看起来像文字被裁掉了
            #    （PowerPoint 里word_wrap 是按整段算的，我第一版按 run 算，
            #     误判了好几页「文字溢出」）。
            chars = []
            for r in runs:
                rsz = r.font.size.pt if r.font.size else size
                rbold = bool(r.font.bold)
                rcol = color
                try:
                    rcol = tuple(r.font.color.rgb)
                except Exception:
                    pass
                rfnt = font(rsz * 96 / 72.0, rbold)
                for ch in r.text:
                    chars.append((ch, rfnt, rcol))
            ls = para.line_spacing or 1.0
            lh = (size * 96 / 72.0) * 1.42 * (ls if isinstance(ls, float) else 1.0)
            sb = para.space_before.pt * 96 / 72.0 if para.space_before else 0
            cy += sb
            maxw = max(20, w - 10)
            cx, cur_w = x + 4, 0.0
            for ch, cfnt, ccol in chars:
                if ch == '\n':
                    cy += lh; cx = x + 4; cur_w = 0.0
                    continue
                cwid = d.textlength(ch, font=cfnt)
                if cur_w + cwid > maxw:
                    cy += lh; cx = x + 4; cur_w = 0.0
                d.text((cx, cy), ch, font=cfnt, fill=ccol)
                cx += cwid; cur_w += cwid
            cy += lh
        # 文字超出形状框 → 记下来（这是最常见的「打开才发现」问题）
        if cy > y + h + 26 and shp.has_text_frame and shp.text_frame.text.strip():
            overflow.append(('TEXT_OVERFLOW', shp.text_frame.text.strip()[:26],
                             round(y), round(cy - (y + h))))
    img.save(os.path.join(OUT, 'p%02d.png' % idx))
    return overflow


def main():
    prs = Presentation(PPTX)
    sw = E(prs.slide_width)
    sh = E(prs.slide_height)
    print('slide size = %.0f x %.0f px, slides = %d' % (sw, sh, len(prs.slides._sldIdLst)))
    bad = 0
    for i, s in enumerate(prs.slides, 1):
        ov = render(i, s, sw, sh)
        if ov:
            bad += 1
            print('[!] p%02d 版式问题：' % i)
            for o in ov[:4]:
                print('     ', o)
    print('预览输出:', OUT)
    print('有问题的页数:', bad)


if __name__ == '__main__':
    main()