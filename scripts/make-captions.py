#!/usr/bin/env python3
"""Render chapter captions for the demo video as transparent 1920x1080 PNGs.

  make-captions.py <out-dir> "Name|Caption text" ...
Writes <out-dir>/<Name>.png. Needs python3-pil and the Inter font (both in the build VM).
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
FONT = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"


def caption(text, path):
    font = ImageFont.truetype(FONT, 34)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font)
    pad_x, pad_y = 26, 16
    bw, bh = (x1 - x0) + pad_x * 2, (y1 - y0) + pad_y * 2
    left, top = 56, H - 56 - bh
    # soft shadow so the label stays readable over bright wallpaper and white pages
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((left, top + 6, left + bw, top + bh + 6), 18, fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((left, top, left + bw, top + bh), 18, fill=(14, 15, 24, 205),
                        outline=(255, 255, 255, 60), width=1)
    d.text((left + pad_x - x0, top + pad_y - y0), text, font=font, fill=(255, 255, 255, 255))
    img.save(path)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for spec in sys.argv[2:]:
        name, text = spec.split("|", 1)
        caption(text, os.path.join(out, name + ".png"))
    print(f"{len(sys.argv) - 2} captions in {out}")


if __name__ == "__main__":
    main()
