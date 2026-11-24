#!/usr/bin/env python3
"""Draw the GlassOS app icons as SVG, in three styles (like iPhone's icon appearance).

    python3 scripts/make-icons.py

Writes three icon themes into overlay/usr/share/icons/:
  Glass        Color: coloured glass tiles with frosted-glass symbols (the default)
  Glass-Clear  Clear: the tile is clear glass and the desktop shows through it
  Glass-Dark   Dark: smoked-glass tiles with the symbol in the app's colour
Settings > Appearance > Icon style switches between them. Anything these themes don't draw comes
from Papirus-Dark (Inherits=), so only app icons are replaced.

One recipe for every icon, so the set reads as a family:
  - 512 grid, squircle tile (superellipse n=5) inset 32, every tile the same size
  - light comes from above: a bright edge along the top of the tile and of every symbol, fading
    down the sides and coming back, fainter, along the bottom where it passes out of the glass
  - symbols are glass, not paint: their fill is tinted by the tile behind them (darker and more
    tinted towards the bottom), and they cast a soft shadow in the tile's own colour
  - one symbol per app, inside a 240-unit live area; strokes 26 units, round caps and joins
  - edges are 8 units wide so they still show as about a pixel at dock size

Only gradients, paths and opacity: no filters, masks or clip paths, so GTK's and fuzzel's SVG
renderers draw them the same way.
"""
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONS_DIR = os.path.join(ROOT, "overlay", "usr", "share", "icons")

S = 512
INSET = 32
STROKE = 26
EDGE = 8
TOP, BOTTOM = 136, 376          # the live area the symbol's lighting is measured over


# ----------------------------------------------------------------------------- colour helpers
def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexc(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def mix(a, b, t):
    """t=0 gives a, t=1 gives b."""
    a, b = rgb(a), rgb(b)
    return hexc(tuple(x + (y - x) * t for x, y in zip(a, b)))


WHITE, BLACK = "#ffffff", "#000000"


# ----------------------------------------------------------------------------- geometry
def squircle(inset=INSET, n=5.0, steps=160):
    a = (S - 2 * inset) / 2
    c = S / 2
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        ct, st = math.cos(t), math.sin(t)
        x = c + a * math.copysign(abs(ct) ** (2 / n), ct)
        y = c + a * math.copysign(abs(st) ** (2 / n), st)
        pts.append(f"{x:.1f},{y:.1f}")
    return "M" + " L".join(pts) + " Z"


SQ = squircle()
SQ_IN = squircle(INSET + 10)


def rrect(x, y, w, h, r):
    return (f"M{x + r},{y} H{x + w - r} Q{x + w},{y} {x + w},{y + r} V{y + h - r} "
            f"Q{x + w},{y + h} {x + w - r},{y + h} H{x + r} Q{x},{y + h} {x},{y + h - r} "
            f"V{y + r} Q{x},{y} {x + r},{y} Z")


def circle(cx, cy, r):
    return f"M{cx - r},{cy} A{r},{r} 0 1 0 {cx + r},{cy} A{r},{r} 0 1 0 {cx - r},{cy} Z"


# ----------------------------------------------------------------------------- symbols
# A symbol is a list of parts:
#   ("fill", path, layer[, round])   a glass shape; layer "front" or "back" (the paler plane behind)
#   ("line", path, width, layer)     a glass stroke
#   ("detail", path, width)          a mark printed on the glass, in the style's detail colour
def files():
    back = ("M140,186 Q140,160 166,160 H212 Q226,160 235,171 L247,186 H346 Q372,186 372,212 "
            "V326 Q372,352 346,352 H166 Q140,352 140,326 Z")
    return [("fill", back, "back"), ("fill", rrect(140, 216, 232, 136, 26), "see")]


def browser():
    """Browser: a glass globe, with a glint where the light catches the sphere."""
    r = 112
    meridian = f"M256,{256 - r} A52,{r} 0 0 1 256,{256 + r} A52,{r} 0 0 1 256,{256 - r} Z"
    lat = " ".join(f"M{256 - math.sqrt(r * r - dy * dy) + 6:.1f},{256 + dy} "
                   f"H{256 + math.sqrt(r * r - dy * dy) - 6:.1f}" for dy in (-54, 54))
    return [("line", meridian, 16, "back"),
            ("line", f"M{256 - r + 4},256 H{256 + r - 4}", 16, "back"),
            ("line", lat, 16, "back"),
            ("line", circle(256, 256, r), 24, "front"),
            ("shine", "M182,214 A84,84 0 0 1 222,170", 12)]


def terminal():
    return [("line", "M180,200 L236,256 L180,312", 28, "front"),
            ("line", "M266,312 H332", 28, "back")]


def editor():
    return [("fill", rrect(170, 140, 172, 232, 30), "front")] + \
        [("detail", f"M206,{y} H{x2}", 18) for y, x2 in ((198, 306), (238, 306), (278, 306), (318, 262))]


def gear_path(teeth, outer, root, top_frac=0.42, base_frac=0.62, phase=0.0):
    """A gear outline: `teeth` trapezoid teeth between radius `root` and `outer`."""
    step = 2 * math.pi / teeth
    d = ""
    for k in range(teeth):
        t = phase + step * k
        for frac, rad in ((-base_frac / 2, root), (-top_frac / 2, outer), (top_frac / 2, outer),
                          (base_frac / 2, root)):
            a = t + frac * step
            x, y = 256 + rad * math.cos(a), 256 + rad * math.sin(a)
            d += ("M" if not d else " L") + f"{x:.1f},{y:.1f}"
        # round valley to the next tooth
        a = t + step - base_frac / 2 * step
        x, y = 256 + root * math.cos(a), 256 + root * math.sin(a)
        d += f" A{root},{root} 0 0 1 {x:.1f},{y:.1f}"
    return d + " Z"


def gear():
    """Settings: a finely toothed outer ring, held to a small hub gear by six spokes."""
    ring = gear_path(28, 130, 116, 0.40, 0.58) + " " + circle(256, 256, 94)
    hub = gear_path(10, 62, 50, 0.42, 0.62, math.pi / 10) + " " + circle(256, 256, 22)
    spokes = " ".join(
        f"M{256 + 50 * math.cos(a):.1f},{256 + 50 * math.sin(a):.1f} "
        f"L{256 + 100 * math.cos(a):.1f},{256 + 100 * math.sin(a):.1f}"
        for a in (math.pi / 6 + k * math.pi / 3 for k in range(6)))
    return [("line", spokes, 16, "back"),
            ("fill", ring, "see", 6, "evenodd"),
            ("fill", hub, "front", 6, "evenodd")]


def lens():
    return [("line", circle(256, 256, 114), STROKE, "back"),
            ("line", "M158,262 H206 L230,212 L266,306 L290,248 H354", 24, "front")]


def sounds():
    bars = ((176, 38), (216, 82), (256, 118), (296, 68), (336, 32))
    return [("line", f"M{x},{256 - h} V{256 + h}", 28, "front") for x, h in bars]


def store():
    """App Store: a shopfront with a striped glass awning."""
    parts = [("fill", rrect(170, 236, 172, 130, 22), "back"),            # the shop
             ("fill", rrect(226, 286, 60, 80, 16), "see")]               # its door
    x0, w, top, drop = 146, 55, 146, 62
    for i in range(4):                                                    # awning stripes
        x = x0 + i * w
        r = w / 2
        d = (f"M{x},{top + 14} Q{x},{top} {x + 14},{top} H{x + w - 14} Q{x + w},{top} {x + w},{top + 14} "
             if i in (0, 3) else f"M{x},{top} H{x + w} ")
        if i == 1 or i == 2:
            d = f"M{x},{top} H{x + w} "
        if i == 0:
            d = f"M{x},{top + 16} Q{x},{top} {x + 16},{top} H{x + w} "
        if i == 3:
            d = f"M{x},{top} H{x + w - 16} Q{x + w},{top} {x + w},{top + 16} "
        d += f"V{top + drop} A{r},{r} 0 0 1 {x},{top + drop} Z"
        parts.append(("fill", d, "front" if i % 2 == 0 else "mid", 4))
    return parts


def calculator():
    return [("fill", rrect(158, 158, 92, 92, 26), "front"), ("fill", rrect(262, 158, 92, 92, 26), "front"),
            ("fill", rrect(158, 262, 92, 92, 26), "front"), ("fill", rrect(262, 262, 92, 92, 26), "back"),
            ("detail", "M204,186 V222 M186,204 H222", 14),            # +
            ("detail", "M290,204 H326", 14),                          # -
            ("detail", "M191,295 L217,321 M217,295 L191,321", 14),    # x
            ("detail", "M290,298 H326 M290,318 H326", 14)]            # =


def help_():
    q = "M208,206 Q208,154 256,154 Q306,154 306,202 Q306,236 276,250 Q256,260 256,284 V292"
    return [("line", q, 40, "front"), ("fill", circle(256, 352, 24), "front")]


def images():
    frame = rrect(146, 166, 220, 180, 30)
    hills = ("M146,320 L218,246 Q232,232 246,246 L290,290 L310,270 Q324,256 338,270 L366,298 "
             "V318 Q366,346 338,346 H174 Q146,346 146,320 Z")
    return [("fill", frame, "back"), ("fill", hills, "front"), ("fill", circle(304, 222, 22), "front")]


def all_apps():
    return [("fill", rrect(158, 158, 92, 92, 28), "front"), ("fill", rrect(262, 158, 92, 92, 28), "back"),
            ("fill", rrect(158, 262, 92, 92, 28), "back"), ("fill", rrect(262, 262, 92, 92, 28), "front")]


# ----------------------------------------------------------------------------- styles
class Color:
    name, theme, title = "color", "Glass", "Color"

    def __init__(self, c1, c2):
        self.c1, self.c2 = c1, c2
        self.light = mix(c1, WHITE, 0.35)

    def tile(self):
        return f'''<linearGradient id="bg" x1="0.2" y1="0" x2="0.8" y2="1">
    <stop offset="0" stop-color="{self.c1}"/><stop offset="1" stop-color="{self.c2}"/></linearGradient>
  <radialGradient id="glow" cx="0.28" cy="0.12" r="0.85">
    <stop offset="0" stop-color="{self.light}" stop-opacity="0.75"/>
    <stop offset="1" stop-color="{self.light}" stop-opacity="0"/></radialGradient>
  <linearGradient id="depth" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0.5" stop-color="#000000" stop-opacity="0"/>
    <stop offset="1" stop-color="#000000" stop-opacity="0.20"/></linearGradient>''', \
            '<path d="{sq}" fill="url(#bg)"/><path d="{sq}" fill="url(#glow)"/><path d="{sq}" fill="url(#depth)"/>'

    def paint(self, layer):
        """(top colour, bottom colour, opacity) for a glass layer: white glass tinted by the tile."""
        if layer == "see":     # see-through glass: what's behind shows through it
            return mix(WHITE, self.c1, 0.10), mix(WHITE, self.c2, 0.25), 0.58
        if layer == "front":
            return mix(WHITE, self.c1, 0.06), mix(WHITE, self.c2, 0.30), 1
        if layer == "mid":
            return mix(WHITE, self.c1, 0.30), mix(WHITE, self.c2, 0.50), 1
        return mix(WHITE, self.c1, 0.45), mix(WHITE, self.c2, 0.62), 1

    def detail(self):
        return mix(self.c2, BLACK, 0.12)

    def shadow(self):
        return mix(self.c2, BLACK, 0.55), 1.0

    tile_edge = (0.95, 0.18, 0.06, 0.45)
    symbol_edge = (1.0, 0.25, 0.10, 0.65)


class Clear(Color):
    name, theme, title = "clear", "Glass-Clear", "Clear"

    def tile(self):
        return '''<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#ffffff" stop-opacity="0.30"/>
    <stop offset="1" stop-color="#ffffff" stop-opacity="0.10"/></linearGradient>
  <radialGradient id="glow" cx="0.28" cy="0.1" r="0.8">
    <stop offset="0" stop-color="#ffffff" stop-opacity="0.22"/>
    <stop offset="1" stop-color="#ffffff" stop-opacity="0"/></radialGradient>''', \
            '<path d="{sq}" fill="url(#bg)"/><path d="{sq}" fill="url(#glow)"/>'

    def paint(self, layer):
        return {"front": (WHITE, WHITE, 0.94), "mid": (WHITE, WHITE, 0.66),
                "see": (WHITE, WHITE, 0.50)}.get(layer, (WHITE, WHITE, 0.40))

    def detail(self):     # clear icons carry no colour at all
        return "#2a2d36"

    def shadow(self):
        return BLACK, 0.45

    tile_edge = (1.0, 0.30, 0.10, 0.55)
    symbol_edge = (1.0, 0.35, 0.15, 0.6)


class Dark(Color):
    name, theme, title = "dark", "Glass-Dark", "Dark"

    def tile(self):
        return f'''<linearGradient id="bg" x1="0.2" y1="0" x2="0.8" y2="1">
    <stop offset="0" stop-color="#30323d"/><stop offset="1" stop-color="#101116"/></linearGradient>
  <radialGradient id="glow" cx="0.5" cy="0.55" r="0.6">
    <stop offset="0" stop-color="{self.c1}" stop-opacity="0.22"/>
    <stop offset="1" stop-color="{self.c1}" stop-opacity="0"/></radialGradient>''', \
            '<path d="{sq}" fill="url(#bg)"/><path d="{sq}" fill="url(#glow)"/>'

    def paint(self, layer):
        top, bot = mix(self.c1, WHITE, 0.25), self.c2
        r, g, b = rgb(self.c1)
        if max(r, g, b) - min(r, g, b) < 40:     # a grey app (Terminal, Settings): a light symbol
            top, bot = "#f2f4f8", "#9298a8"
        if layer == "front":
            return top, bot, 1
        if layer == "see":
            return top, bot, 0.55
        if layer == "mid":
            return mix(top, "#101116", 0.3), mix(bot, "#101116", 0.3), 1
        return mix(top, "#101116", 0.5), mix(bot, "#101116", 0.5), 1

    def detail(self):
        return "#14151b"

    def shadow(self):
        return BLACK, 1.0

    tile_edge = (0.55, 0.12, 0.04, 0.25)
    symbol_edge = (0.85, 0.20, 0.05, 0.45)


STYLES = (Color, Clear, Dark)


# ----------------------------------------------------------------------------- drawing
def edge_gradient(gid, stops, y0, y1, units="userSpaceOnUse"):
    a, b, c, d = stops
    if units == "userSpaceOnUse":
        head = f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="0" y1="{y0}" x2="0" y2="{y1}">'
    else:
        head = f'<linearGradient id="{gid}" x1="0.3" y1="0" x2="0.7" y2="1">'
    return (head + f'<stop offset="0" stop-color="#fff" stop-opacity="{a}"/>'
            f'<stop offset="0.3" stop-color="#fff" stop-opacity="{b}"/>'
            f'<stop offset="0.7" stop-color="#fff" stop-opacity="{c}"/>'
            f'<stop offset="1" stop-color="#fff" stop-opacity="{d}"/></linearGradient>')


def render(style, parts):
    defs, tile_body = style.tile()
    defs += "\n  " + edge_gradient("tedge", style.tile_edge, 0, 1, "box")
    defs += "\n  " + edge_gradient("sedge", style.symbol_edge, TOP, BOTTOM)
    for layer in ("front", "mid", "back", "see"):
        top, bot, op = style.paint(layer)
        defs += (f'\n  <linearGradient id="g-{layer}" gradientUnits="userSpaceOnUse" x1="0" y1="{TOP}" x2="0" '
                 f'y2="{BOTTOM}"><stop offset="0" stop-color="{top}" stop-opacity="{op}"/>'
                 f'<stop offset="1" stop-color="{bot}" stop-opacity="{op}"/></linearGradient>')
    out = [f"<defs>\n  {defs}\n</defs>", tile_body.format(sq=SQ)]

    # a soft shadow under the symbol, in the tile's own colour
    sh, k = style.shadow()
    for dy, op in ((16, 0.06), (9, 0.10), (4, 0.14)):
        o = op * k
        out.append(f'<g transform="translate(0,{dy})">')
        for p in parts:
            if p[0] == "fill":
                w = (p[3] if len(p) > 3 else EDGE) + EDGE / 2
                rule = p[4] if len(p) > 4 else "nonzero"
                out.append(f'<path d="{p[1]}" fill="{sh}" fill-opacity="{o:.3f}" fill-rule="{rule}" '
                           f'stroke="{sh}" stroke-opacity="{o:.3f}" stroke-width="{w}" stroke-linejoin="round"/>')
            elif p[0] == "line":
                out.append(f'<path d="{p[1]}" fill="none" stroke="{sh}" stroke-opacity="{o:.3f}" '
                           f'stroke-width="{p[2]}" stroke-linecap="round" stroke-linejoin="round"/>')
        out.append("</g>")

    # the glass symbol: a bright edge lit from above, then its tinted body inside that edge
    for p in parts:
        if p[0] == "fill":
            d, layer = p[1], p[2]
            w = p[3] if len(p) > 3 else EDGE          # every shape gets slightly rounded corners
            rule = p[4] if len(p) > 4 else "nonzero"
            out.append(f'<path d="{d}" fill="none" stroke="url(#sedge)" stroke-width="{w + EDGE / 2}" '
                       f'stroke-linejoin="round"/>')
            out.append(f'<path d="{d}" fill="url(#g-{layer})" fill-rule="{rule}" stroke="url(#g-{layer})" '
                       f'stroke-width="{max(w - EDGE / 2, 0)}" stroke-linejoin="round"/>')
        elif p[0] == "line":
            d, w, layer = p[1], p[2], p[3]
            out.append(f'<path d="{d}" fill="none" stroke="url(#sedge)" stroke-width="{w}" '
                       f'stroke-linecap="round" stroke-linejoin="round"/>')
            out.append(f'<path d="{d}" fill="none" stroke="url(#g-{layer})" stroke-width="{w - EDGE}" '
                       f'stroke-linecap="round" stroke-linejoin="round"/>')
    for p in parts:
        if p[0] == "shine":
            out.append(f'<path d="{p[1]}" fill="none" stroke="#ffffff" stroke-opacity="0.85" '
                       f'stroke-width="{p[2]}" stroke-linecap="round"/>')
        if p[0] == "detail":
            out.append(f'<path d="{p[1]}" fill="none" stroke="{style.detail()}" stroke-width="{p[2]}" '
                       f'stroke-linecap="round" stroke-linejoin="round"/>')

    # the tile's own edges: a bright rim, and a fainter one just inside it for the glass's thickness
    out.append(f'<path d="{SQ}" fill="none" stroke="url(#tedge)" stroke-width="{EDGE}"/>')
    out.append(f'<path d="{SQ_IN}" fill="none" stroke="#ffffff" stroke-opacity="0.08" stroke-width="2"/>')
    body = "\n".join(out)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{S}" height="{S}" viewBox="0 0 {S} {S}">\n'
            f"{body}\n</svg>\n")


# ----------------------------------------------------------------------------- the set
# name, colours (top, bottom), symbol, other icon names the same picture answers to
ICONS = [
    ("glass-files", ("#5aa2ff", "#1d5be0"), files,
     ["org.xfce.thunar", "Thunar", "thunar", "system-file-manager", "file-manager"]),
    ("glass-browser", ("#9a7dff", "#4a2fd0"), browser, ["web-browser", "os.glass.Browser"]),
    ("glass-terminal", ("#565c6c", "#17191f"), terminal,
     ["foot", "org.codeberg.dnkl.foot", "utilities-terminal", "terminal"]),
    ("glass-editor", ("#f0a582", "#c45a38"), editor,
     ["org.xfce.mousepad", "mousepad", "accessories-text-editor", "text-editor"]),
    ("glass-settings", ("#7c8395", "#353b4b"), gear, ["preferences-system", "preferences-desktop", "system-software-update"]),
    ("glass-lens", ("#7482ff", "#1fb0c2"), lens, ["utilities-system-monitor"]),
    ("glass-sounds", ("#c780ff", "#ec4b94"), sounds, []),
    ("glass-store", ("#6e8bff", "#3b3fd8"), store, ["system-software-install"]),
    ("glass-calculator", ("#ffb062", "#e95e22"), calculator,
     ["accessories-calculator", "org.gnome.Calculator"]),
    ("glass-help", ("#4fdcae", "#0f8a7a"), help_, ["help-browser"]),
    ("glass-images", ("#ff93a7", "#d6406a"), images,
     ["imv", "multimedia-photo-viewer", "image-viewer"]),
    ("glass-apps", ("#8e95a8", "#40465a"), all_apps, []),
]


INDEX = """[Icon Theme]
Name={theme}
Comment=GlassOS app icons ({title}); everything else comes from Papirus-Dark
Inherits=Papirus-Dark,hicolor
Directories=scalable/apps

[scalable/apps]
Size=64
MinSize=16
MaxSize=512
Type=Scalable
Context=Applications
"""


def main():
    total = 0
    for style_cls in STYLES:
        out = os.path.join(ICONS_DIR, style_cls.theme)
        apps = os.path.join(out, "scalable", "apps")
        os.makedirs(apps, exist_ok=True)
        for f in os.listdir(apps):
            if f.endswith(".svg"):
                os.remove(os.path.join(apps, f))
        for name, (c1, c2), symbol, aliases in ICONS:
            data = render(style_cls(c1, c2), symbol())
            for n in [name] + aliases:   # copies, not symlinks, so the repo works on Windows too
                with open(os.path.join(apps, n + ".svg"), "w", newline="\n") as f:
                    f.write(data)
                total += 1
        with open(os.path.join(out, "index.theme"), "w", newline="\n") as f:
            f.write(INDEX.format(theme=style_cls.theme, title=style_cls.title))
    print(f"wrote {total} icons in {len(STYLES)} styles to {ICONS_DIR}")


if __name__ == "__main__":
    main()
