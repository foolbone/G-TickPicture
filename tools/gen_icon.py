# -*- coding: utf-8 -*-
"""Generate launcher icons for 集刻-采集 (G-TickPicture).

Design language (must match lib/app/theme.dart):
  deep navy radial background + four off-white viewfinder corner
  brackets + central vermilion shutter disc with focus ring & dot.
  All motif elements stay inside the inscribed circle so circular
  launcher masks never clip them.

Rendered at 4096 px, downscaled to 1024 with LANCZOS -> crisp edges.

Outputs (D:\\G-TickPicture\\app\\assets\\icon\\):
  app_icon.png             1024x1024 RGB  full-bleed (legacy mipmaps)
  app_icon_foreground.png  1024x1024 RGBA transparent, identical motif
                           (adaptive foreground over solid navy bg)
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

OUT_DIR = r"D:\G-TickPicture\app\assets\icon"
S = 4096          # working canvas (supersampled)
FINAL = 1024      # output size
CX = CY = S // 2

# -- theme colors (lib/app/theme.dart) -----------------------------
NAVY2     = (20, 57, 92)      # 0x14395C gradient center
NAVY_DEEP = (7, 24, 43)       # gradient edge
CREAM     = (245, 240, 230)   # off-white viewfinder brackets
VERM_HI   = (216, 88, 62)     # shutter disc highlight (top-left)
VERM_LO   = (170, 53, 34)     # shutter disc shade (bottom-right)
SHADOW    = (4, 14, 28, 130)  # soft shadow under the disc

# -- motif geometry (px on the 4096 canvas) ------------------------
# inscribed-circle radius = 2048; keep max extent <= ~1980
BR_C   = 1380   # bracket corner offset from center (diag = 1952)
BR_ARM = 350    # bracket arm length
BR_R   = 52     # bracket half stroke width
DISC_R = 800    # shutter disc radius
RING_R = 450    # focus ring radius
RING_W = 52     # focus ring stroke width
DOT_R  = 95     # center dot radius


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def radial_bg(size):
    """Radial gradient: brighter navy center -> deep navy edges."""
    small = 512
    sm = Image.new("RGB", (small, small))
    px = sm.load()
    c = small / 2.0
    maxd = math.hypot(c, c)
    for y in range(small):
        for x in range(small):
            t = math.hypot(x - c, y - c) / maxd
            px[x, y] = lerp(NAVY2, NAVY_DEEP, t ** 1.35)
    return sm.resize((size, size), Image.BILINEAR)


def disc_gradient(radius):
    """Diagonal light gradient clipped to a circle, returned as RGBA."""
    d = radius * 2
    small = 256
    sm = Image.new("RGB", (small, small))
    px = sm.load()
    for y in range(small):
        for x in range(small):
            t = (x + y) / (2.0 * (small - 1))
            px[x, y] = lerp(VERM_HI, VERM_LO, t)
    g = sm.resize((d, d), Image.BILINEAR)
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
    out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    out.paste(g, (0, 0), mask)
    return out


def draw_bracket(draw, cx, cy, dx, dy):
    """One corner bracket: two thick segments with round caps.
    (cx, cy) = corner point; (dx, dy) points into the canvas."""
    p0 = (cx + dx * BR_ARM, cy)
    p2 = (cx, cy + dy * BR_ARM)
    draw.line([p0, (cx, cy)], fill=CREAM + (255,), width=BR_R * 2)
    draw.line([(cx, cy), p2], fill=CREAM + (255,), width=BR_R * 2)
    for (x, y) in (p0, (cx, cy), p2):
        draw.ellipse([x - BR_R, y - BR_R, x + BR_R, y + BR_R],
                     fill=CREAM + (255,))


def draw_motif(img, with_shadow=True):
    """Draw brackets + shutter disc assembly, centered on the canvas."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    c, cy = CX, CY

    # four viewfinder corner brackets
    for (bx, by, dx, dy) in ((c - BR_C, cy - BR_C, +1, +1),
                             (c + BR_C, cy - BR_C, -1, +1),
                             (c - BR_C, cy + BR_C, +1, -1),
                             (c + BR_C, cy + BR_C, -1, -1)):
        draw_bracket(ld, bx, by, dx, dy)

    # soft shadow under the disc (legacy only; adaptive bg is flat)
    if with_shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        off = 90
        ImageDraw.Draw(sh).ellipse(
            [CX - DISC_R, CY - DISC_R + off,
             CX + DISC_R, CY + DISC_R + off], fill=SHADOW)
        sh = sh.filter(ImageFilter.GaussianBlur(80))
        img.alpha_composite(sh)

    img.alpha_composite(layer)
    img.alpha_composite(disc_gradient(DISC_R), (CX - DISC_R, CY - DISC_R))

    # focus ring + center dot
    d2 = ImageDraw.Draw(img)
    d2.ellipse([CX - RING_R, CY - RING_R, CX + RING_R, CY + RING_R],
               outline=CREAM + (255,), width=RING_W)
    d2.ellipse([CX - DOT_R, CY - DOT_R, CX + DOT_R, CY + DOT_R],
               fill=CREAM + (255,))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # 1) legacy full-bleed icon (radial navy bg + motif)
    icon = radial_bg(S).convert("RGBA")
    draw_motif(icon, with_shadow=True)
    icon.convert("RGB").resize((FINAL, FINAL), Image.LANCZOS).save(
        os.path.join(OUT_DIR, "app_icon.png"), "PNG")

    # 2) adaptive foreground: transparent, same motif geometry
    fg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw_motif(fg, with_shadow=False)
    fg.resize((FINAL, FINAL), Image.LANCZOS).save(
        os.path.join(OUT_DIR, "app_icon_foreground.png"), "PNG")

    print("OK  app_icon.png + app_icon_foreground.png ->", OUT_DIR)


if __name__ == "__main__":
    main()
