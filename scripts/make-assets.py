#!/usr/bin/env python3
"""Render every piece of GlassOS artwork from code (all original, no third-party art).

    make-assets.py <output-dir>

Produces wallpapers, the GlassOS logo + app icons, the GRUB theme images/fonts and the
Plymouth boot-splash images. Requires python3-pil, python3-numpy and grub-mkfont.
"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

OUT = sys.argv[1] if len(sys.argv) > 1 else "assets/generated"
INTER = "/usr/share/fonts/opentype/inter"
DEJAVU_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
rng = np.random.default_rng(7)


def mkdir(*parts):
    p = os.path.join(OUT, *parts)
    os.makedirs(p, exist_ok=True)
    return p


def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


# ---------------------------------------------------------------------------------------
# Wallpapers: domain-warped flowing colour fields ("liquid glass ribbons")
# ---------------------------------------------------------------------------------------
def wallpaper(w, h, palette, seed, base_top, base_bot):
    r = np.random.default_rng(seed)
    sw, sh = w // 4, h // 4
    y, x = np.mgrid[0:sh, 0:sw].astype(np.float32)
    x /= sw
    y /= sh
    aspect = sw / sh
    xa = x * aspect

    img = (1 - y)[..., None] * hexrgb(base_top) + y[..., None] * hexrgb(base_bot)

    # flowing ribbons: each ribbon is a warped diagonal band with a soft glassy edge
    for i, col in enumerate(palette):
        ph = r.uniform(0, 6.28, 4)
        fr = r.uniform(1.2, 2.6, 3)
        u = xa + 0.22 * np.sin(fr[0] * y * 3.1 + ph[0]) + 0.10 * np.sin(fr[1] * xa * 4.3 + ph[1])
        v = y + 0.18 * np.sin(fr[2] * xa * 2.3 + ph[2]) + 0.06 * np.sin(y * 7.0 + ph[3])
        centre = r.uniform(-0.2, 1.2) + i * 0.08
        d = (u * 0.55 + v * 0.95) - centre
        width = r.uniform(0.09, 0.2)
        band = np.exp(-(d / width) ** 2)
        edge = np.exp(-((d - width * 0.75) / (width * 0.18)) ** 2) * 0.35  # bright rim
        glow = band * r.uniform(0.55, 0.9) + edge
        c = hexrgb(col)
        img = 1 - (1 - img) * (1 - np.clip(glow[..., None] * c, 0, 1))  # screen blend

    # soft light blobs for depth
    for _ in range(4):
        cx, cy = r.uniform(0, aspect), r.uniform(0, 1)
        s = r.uniform(0.15, 0.35)
        blob = np.exp(-(((xa - cx) ** 2 + (y - cy) ** 2) / (2 * s * s)))
        c = hexrgb(palette[r.integers(len(palette))]) * 0.35
        img = 1 - (1 - img) * (1 - blob[..., None] * c)

    # vignette
    vig = 1 - 0.45 * (((x - 0.5) * 1.3) ** 2 + ((y - 0.5) * 1.5) ** 2)
    img *= np.clip(vig, 0.4, 1)[..., None]

    small = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    small = small.filter(ImageFilter.GaussianBlur(2))
    big = small.resize((w, h), Image.BICUBIC)
    arr = np.asarray(big).astype(np.float32)
    arr += r.normal(0, 1.6, arr.shape)  # film grain kills gradient banding
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------------------------------
# Logo + icons
# ---------------------------------------------------------------------------------------
def linear_gradient(size, c1, c2, angle_deg=45):
    w, h = size
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    a = np.deg2rad(angle_deg)
    t = (x / w) * np.cos(a) + (y / h) * np.sin(a)
    t = (t - t.min()) / max(1e-6, t.max() - t.min())
    c1 = np.array(c1, np.float32)
    c2 = np.array(c2, np.float32)
    rgba = (1 - t)[..., None] * c1 + t[..., None] * c2
    return Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), "RGBA")


def rr_mask(size, box, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


def glass_pane(canvas, box, radius, tint, alpha, frost=True, highlight=1.0):
    """Composite one frosted-glass pane onto canvas (RGBA) in place."""
    size = canvas.size
    mask = rr_mask(size, box, radius)
    if frost:
        blurred = canvas.filter(ImageFilter.GaussianBlur(radius * 0.35))
        canvas.paste(blurred, (0, 0), mask)
    x0, y0, x1, y1 = box
    grad = linear_gradient(size, (*tint[0], int(255 * alpha)), (*tint[1], int(255 * alpha * 0.75)), 55)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.paste(grad, (0, 0), mask)
    canvas.alpha_composite(layer)
    # glossy top highlight
    gloss = Image.new("L", size, 0)
    gd = ImageDraw.Draw(gloss)
    gd.ellipse((x0 - (x1 - x0) * 0.2, y0 - (y1 - y0) * 0.55, x1 + (x1 - x0) * 0.2, y0 + (y1 - y0) * 0.42),
               fill=int(70 * highlight))
    gloss = ImageChops.multiply(gloss, mask).filter(ImageFilter.GaussianBlur(radius * 0.15))
    white = Image.new("RGBA", size, (255, 255, 255, 0))
    white.putalpha(gloss)
    canvas.alpha_composite(white)
    # specular rim: bright top-left, fading to bottom-right
    rim = Image.new("L", size, 0)
    stroke = max(2, int(radius * 0.09))
    ImageDraw.Draw(rim).rounded_rectangle(box, radius=radius, outline=255, width=stroke)
    fade = linear_gradient(size, (255, 255, 255, 230), (255, 255, 255, 40), 45).getchannel("A")
    rim = ImageChops.multiply(rim, fade)
    rim_layer = Image.new("RGBA", size, (255, 255, 255, 0))
    rim_layer.putalpha(ImageChops.multiply(rim, Image.new("L", size, int(255 * highlight))))
    canvas.alpha_composite(rim_layer)


def logo(px):
    S = px * 4  # supersample
    c = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    u = S / 100.0
    # back pane (violet), middle pane (blue), front pane (frosted clear)
    glass_pane(c, (int(8 * u), int(8 * u), int(62 * u), int(62 * u)), int(15 * u),
               ((160, 92, 255), (96, 60, 230)), 0.95, frost=False)
    glass_pane(c, (int(23 * u), int(23 * u), int(77 * u), int(77 * u)), int(15 * u),
               ((64, 150, 255), (40, 220, 230)), 0.85, frost=True)
    glass_pane(c, (int(38 * u), int(38 * u), int(92 * u), int(92 * u)), int(15 * u),
               ((255, 255, 255), (200, 240, 255)), 0.32, frost=True, highlight=1.3)
    return c.resize((px, px), Image.LANCZOS)


def logo_symbolic(px):
    S = px * 4
    c = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(c)
    u = S / 100.0
    w = int(8 * u)
    d.rounded_rectangle((int(6 * u), int(6 * u), int(64 * u), int(64 * u)), radius=int(17 * u),
                        outline=(255, 255, 255, 255), width=w)
    d.rounded_rectangle((int(36 * u), int(36 * u), int(94 * u), int(94 * u)), radius=int(17 * u),
                        fill=(255, 255, 255, 235))
    return c.resize((px, px), Image.LANCZOS)


def app_tile(px, tint, draw_fn):
    S = px * 4
    c = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    u = S / 100.0
    glass_pane(c, (int(6 * u), int(6 * u), int(94 * u), int(94 * u)), int(22 * u), tint, 0.95, frost=False)
    draw_fn(c, u)
    return c.resize((px, px), Image.LANCZOS)


def draw_lens(c, u):
    d = ImageDraw.Draw(c)
    # bars ("where your hardware goes")
    for i, hgt in enumerate((26, 44, 34, 58)):
        x = 26 + i * 13
        d.rounded_rectangle((int(x * u), int((74 - hgt) * u), int((x + 8) * u), int(74 * u)),
                            radius=int(3 * u), fill=(255, 255, 255, 220))
    d.ellipse((int(18 * u), int(18 * u), int(82 * u), int(82 * u)), outline=(255, 255, 255, 200),
              width=int(5 * u))


def draw_wave(c, u):
    d = ImageDraw.Draw(c)
    pts = []
    for i in range(0, 101):
        t = i / 100.0
        x = 18 + t * 64
        env = np.sin(np.pi * t) ** 1.5
        y = 50 + np.sin(t * np.pi * 6) * 22 * env
        pts.append((x * u, y * u))
    d.line(pts, fill=(255, 255, 255, 235), width=int(5 * u), joint="curve")


def draw_gear(c, u):
    """Settings: a plain gear, the symbol people already read as "settings"."""
    S = c.size[0]
    layer = Image.new("RGBA", c.size, (0, 0, 0, 0))
    teeth, r_out, r_in = 8, 33, 25
    pts = []
    for i in range(teeth * 4):
        a = 2 * np.pi * i / (teeth * 4) - np.pi / 2
        r = r_out if i % 4 in (0, 1) else r_in
        # widen each tooth slightly at its root so it reads as a gear, not a star
        a += (np.pi / (teeth * 8)) * (1 if i % 4 == 2 else -1 if i % 4 == 3 else 0)
        pts.append((50 * u + r * u * np.cos(a), 50 * u + r * u * np.sin(a)))
    d = ImageDraw.Draw(layer)
    d.polygon(pts, fill=(255, 255, 255, 235))
    d.ellipse((int(22 * u), int(22 * u), int(78 * u), int(78 * u)), fill=(255, 255, 255, 235))
    hole = Image.new("L", c.size, 255)
    ImageDraw.Draw(hole).ellipse((int(39 * u), int(39 * u), int(61 * u), int(61 * u)), fill=0)
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), hole))
    c.alpha_composite(layer.filter(ImageFilter.GaussianBlur(S / 1600)))


def draw_store(c, u):
    """App Store: an arrow dropping into a tray, i.e. "get this app"."""
    d = ImageDraw.Draw(c)
    w = (255, 255, 255, 235)
    d.rounded_rectangle((int(46 * u), int(20 * u), int(54 * u), int(52 * u)), radius=int(3 * u), fill=w)
    d.polygon([(33 * u, 46 * u), (67 * u, 46 * u), (50 * u, 64 * u)], fill=w)
    t = int(7 * u)
    d.line([(24 * u, 58 * u), (24 * u, 72 * u)], fill=w, width=t)
    d.line([(76 * u, 58 * u), (76 * u, 72 * u)], fill=w, width=t)
    d.line([(24 * u, 75 * u), (76 * u, 75 * u)], fill=w, width=t)
    for x in (24, 76):
        d.ellipse((int((x - 3.5) * u), int(54.5 * u), int((x + 3.5) * u), int(61.5 * u)), fill=w)
    d.pieslice((int(20.5 * u), int(68.5 * u), int(34.5 * u), int(78.5 * u)), 90, 180, fill=w)
    d.pieslice((int(65.5 * u), int(68.5 * u), int(79.5 * u), int(78.5 * u)), 0, 90, fill=w)


# ---------------------------------------------------------------------------------------
# 9-slice glass boxes for GRUB
# ---------------------------------------------------------------------------------------
def nine_slice(dirpath, prefix, r, fill_a, border_a, top_a=None, pad=8):
    W = H = 2 * r + pad
    S = 4
    big = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, W * S - 1, H * S - 1), radius=r * S, fill=(255, 255, 255, fill_a),
                        outline=(255, 255, 255, border_a), width=max(1, int(1.5 * S)))
    if top_a:
        # brighter top rim
        d.arc((0, 0, 2 * r * S, 2 * r * S), 180, 270, fill=(255, 255, 255, top_a), width=int(1.5 * S))
        d.arc((W * S - 2 * r * S - 1, 0, W * S - 1, 2 * r * S), 270, 360, fill=(255, 255, 255, top_a),
              width=int(1.5 * S))
        d.line((r * S, 0, W * S - r * S, 0), fill=(255, 255, 255, top_a), width=int(1.5 * S))
    img = big.resize((W, H), Image.LANCZOS)
    boxes = {
        "nw": (0, 0, r, r), "n": (r, 0, W - r, r), "ne": (W - r, 0, W, r),
        "w": (0, r, r, H - r), "c": (r, r, W - r, H - r), "e": (W - r, r, W, H - r),
        "sw": (0, H - r, r, H), "s": (r, H - r, W - r, H), "se": (W - r, H - r, W, H),
    }
    for k, b in boxes.items():
        img.crop(b).save(os.path.join(dirpath, f"{prefix}_{k}.png"))


def grub_fonts(dirpath):
    fonts = [
        ("Inter-Regular.otf", 16, "Inter Regular"), ("Inter-Regular.otf", 20, "Inter Regular"),
        ("Inter-Regular.otf", 24, "Inter Regular"), ("Inter-SemiBold.otf", 20, "Inter SemiBold"),
        ("Inter-Bold.otf", 40, "Inter Bold"),
    ]
    for f, size, name in fonts:
        out = os.path.join(dirpath, f"{name.lower().replace(' ', '-')}-{size}.pf2")
        subprocess.run(["grub-mkfont", "-s", str(size), "-n", name, "-o", out, os.path.join(INTER, f)],
                       check=True)
    subprocess.run(["grub-mkfont", "-s", "16", "-n", "DejaVu Sans Mono", "-o",
                    os.path.join(dirpath, "dejavu-sans-mono-16.pf2"), DEJAVU_MONO], check=True)


def text_image(text, font_path, size, fill=(255, 255, 255, 255), tracking=0):
    font = ImageFont.truetype(font_path, size * 4)
    l, t, r, b = font.getbbox(text)
    w = (r - l) + tracking * 4 * max(0, len(text) - 1) + 16
    img = Image.new("RGBA", (w, (b - t) + 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 8 - l
    for ch in text:
        d.text((x, 8 - t), ch, font=font, fill=fill)
        x += font.getlength(ch) + tracking * 4
    return img.resize((max(1, img.width // 4), max(1, img.height // 4)), Image.LANCZOS)


def pill(w, h, rgba):
    S = 4
    img = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, w * S - 1, h * S - 1), radius=h * S // 2, fill=rgba)
    return img.resize((w, h), Image.LANCZOS)


def main():
    wp_dir = mkdir("wallpapers")
    icon_dir = mkdir("icons")
    grub_dir = mkdir("grub-theme")
    ply_dir = mkdir("plymouth")

    prism = wallpaper(3840, 2160, ["#5b2ee0", "#2f7bff", "#29d3c9", "#d14fd8", "#7a5cff", "#ff9a7a"],
                      seed=11, base_top="#07081a", base_bot="#120a2a")
    prism.save(os.path.join(wp_dir, "prism.jpg"), quality=92)
    tide = wallpaper(3840, 2160, ["#0f9bd8", "#29d3a0", "#3a5cff", "#9be7ff", "#1b6fe0"],
                     seed=23, base_top="#03121c", base_bot="#061a2e")
    tide.save(os.path.join(wp_dir, "tide.jpg"), quality=92)
    ember = wallpaper(3840, 2160, ["#ff6a3d", "#ff3d8b", "#ffb347", "#b83dff", "#ff8f6b"],
                      seed=5, base_top="#14060c", base_bot="#1f0a14")
    ember.save(os.path.join(wp_dir, "ember.jpg"), quality=92)
    print("wallpapers done")

    big = logo(1024)
    for s in (16, 24, 32, 48, 64, 128, 256, 512):
        big.resize((s, s), Image.LANCZOS).save(os.path.join(icon_dir, f"glassos-{s}.png"))
    logo_symbolic(64).save(os.path.join(icon_dir, "glassos-symbolic.png"))
    lens = app_tile(512, ((70, 130, 255), (60, 220, 210)), draw_lens)
    sounds = app_tile(512, ((190, 80, 255), (255, 90, 160)), draw_wave)
    settings = app_tile(512, ((128, 138, 170), (70, 78, 108)), draw_gear)
    store = app_tile(512, ((60, 200, 120), (20, 150, 170)), draw_store)
    for s in (16, 24, 32, 48, 64, 128, 256, 512):
        for name, img in (("glass-lens", lens), ("glass-sounds", sounds), ("glass-settings", settings),
                          ("glass-store", store)):
            img.resize((s, s), Image.LANCZOS).save(os.path.join(icon_dir, f"{name}-{s}.png"))
    print("icons done")

    # GRUB: pre-blurred, darkened wallpaper so the translucent menu reads as frosted glass
    bg = prism.resize((1920, 1080), Image.LANCZOS).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", bg.size, (6, 6, 16)), 0.35)
    bg.save(os.path.join(grub_dir, "background.jpg"), quality=90)
    big.resize((112, 112), Image.LANCZOS).save(os.path.join(grub_dir, "logo.png"))
    nine_slice(grub_dir, "menu", 26, fill_a=26, border_a=60, top_a=120)
    nine_slice(grub_dir, "select", 9, fill_a=48, border_a=110, top_a=170, pad=4)
    nine_slice(grub_dir, "progress_bar", 3, fill_a=40, border_a=0, pad=4)
    nine_slice(grub_dir, "progress_highlight", 3, fill_a=230, border_a=0, pad=4)
    grub_fonts(grub_dir)
    print("grub theme done")

    # Plymouth boot splash
    pbg = prism.resize((960, 540), Image.LANCZOS).filter(ImageFilter.GaussianBlur(14))
    pbg = Image.blend(pbg, Image.new("RGB", pbg.size, (6, 6, 16)), 0.45)
    pbg.save(os.path.join(ply_dir, "background.png"))
    big.resize((150, 150), Image.LANCZOS).save(os.path.join(ply_dir, "logo.png"))
    text_image("GlassOS", os.path.join(INTER, "Inter-SemiBold.otf"), 34, tracking=1).save(
        os.path.join(ply_dir, "wordmark.png"))
    pill(220, 6, (255, 255, 255, 46)).save(os.path.join(ply_dir, "track.png"))
    pill(220, 6, (255, 255, 255, 235)).save(os.path.join(ply_dir, "fill.png"))
    pill(60, 6, (255, 255, 255, 235)).save(os.path.join(ply_dir, "shimmer.png"))
    print("plymouth done")


if __name__ == "__main__":
    main()
