#!/usr/bin/python3
"""Glass Lens - see exactly where your computer's hardware is going.

Part of GlassOS. Reads only local kernel accounting; sends nothing anywhere.
Usage: glass-lens [--page welcome|overview|apps|network|hardware|sounds|about]
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, "/usr/lib/glassos/lens")
sys.path.insert(0, "/usr/lib/glassos")

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

import glasssound as gs  # noqa: E402
import glassui  # noqa: E402
import sysinfo as si  # noqa: E402

APP_ID = "os.glass.Lens"
REFRESH_MS = 2000
C = {k: v[1] for k, v in si.CATEGORIES.items()}

CSS = """
window.lens { color: #f2f3f8; }
window.lens headerbar { background: transparent; box-shadow: none; border: none; min-height: 44px; }
window.lens headerbar .title { font-weight: 700; }
.sidebar-pane { background: alpha(#ffffff, 0.035); border-right: 1px solid alpha(#ffffff, 0.07); }
.sidebar-pane list { background: transparent; }
.sidebar-pane row { padding: 9px 12px; margin: 2px 10px; border-radius: 11px; color: alpha(#ffffff, 0.85); }
.sidebar-pane row:selected { background: alpha(#ffffff, 0.14); color: #ffffff; box-shadow: inset 0 1px alpha(#ffffff, 0.12); }
.sidebar-pane row:hover:not(:selected) { background: alpha(#ffffff, 0.06); }
.brand { font-weight: 800; font-size: 15px; padding: 6px 14px 14px 14px; }
.page { padding: 26px 32px 40px 32px; }
.page-title { font-size: 28px; font-weight: 800; }
.page-sub { color: alpha(#ffffff, 0.86); margin-bottom: 8px; }
.card {
  background: alpha(#ffffff, 0.065);
  border: 1px solid alpha(#ffffff, 0.09);
  border-top-color: alpha(#ffffff, 0.2);
  border-radius: 18px;
  padding: 16px 18px;
  box-shadow: inset 0 1px alpha(#ffffff, 0.05);
}
.card-title { font-weight: 700; font-size: 14px; color: alpha(#ffffff, 0.9); }
.card-sub { color: alpha(#ffffff, 0.85); font-size: 12px; }
.big { font-size: 30px; font-weight: 800; font-feature-settings: "tnum"; }
.mid { font-size: 18px; font-weight: 700; font-feature-settings: "tnum"; }
.donut-big { font-size: 26px; font-weight: 800; font-feature-settings: "tnum"; }
.num { font-feature-settings: "tnum"; }
.dim { color: alpha(#ffffff, 0.85); }
.small { font-size: 12px; }
.mono { font-family: "JetBrains Mono", monospace; font-size: 12px; }
.ok { color: #5fe3a1; }
.warn { color: #ffd479; }
.bad { color: #ff8a8a; }
.tag { font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 99px; }
.dot { min-width: 10px; min-height: 10px; border-radius: 5px; }
.grow-row { padding: 9px 4px; border-bottom: 1px solid alpha(#ffffff, 0.06); }
list.plain, list.plain row { background: transparent; }
list.plain row { border-radius: 10px; }
list.plain row:hover { background: alpha(#ffffff, 0.04); }
button.pill { border-radius: 99px; padding: 6px 16px; background: alpha(#ffffff, 0.12); border: 1px solid alpha(#ffffff, 0.16); box-shadow: none; color: #fff; }
button.pill:hover { background: alpha(#ffffff, 0.2); }
button.accent { background: alpha(#6aa8ff, 0.55); border-color: alpha(#ffffff, 0.3); }
button.accent:hover { background: alpha(#6aa8ff, 0.75); }
button.flat-icon { background: none; border: none; box-shadow: none; padding: 4px; border-radius: 99px; }
button.flat-icon:hover { background: alpha(#ffffff, 0.14); }
togglebutton.filter, button.filter { border-radius: 99px; padding: 4px 14px; background: alpha(#ffffff, 0.06); border: 1px solid alpha(#ffffff, 0.1); box-shadow: none; }
togglebutton.filter:checked { background: alpha(#ffffff, 0.2); }
.hero-title { font-size: 40px; font-weight: 800; }
.hero-sub { font-size: 16px; color: alpha(#ffffff, 0.86); }
.kbd { font-family: "JetBrains Mono", monospace; font-size: 12px; padding: 2px 8px; border-radius: 7px;
       background: alpha(#ffffff, 0.12); border: 1px solid alpha(#ffffff, 0.18); }
.check { color: #5fe3a1; font-weight: 800; }
scale trough { background: alpha(#ffffff, 0.14); border-radius: 99px; min-height: 6px; }
scale highlight { background: alpha(#ffffff, 0.85); border-radius: 99px; }
scale slider { background: #ffffff; border-radius: 99px; min-width: 18px; min-height: 18px; margin: -6px; box-shadow: 0 1px 4px alpha(#000, 0.4); }
entry { background: alpha(#ffffff, 0.08); border: 1px solid alpha(#ffffff, 0.14); border-radius: 10px; color: #fff; }
dropdown > button { border-radius: 10px; background: alpha(#ffffff, 0.1); border: 1px solid alpha(#ffffff, 0.14); box-shadow: none; }
expander title { padding: 6px 0; }
"""


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def label(text="", cls=None, xalign=0.0, wrap=False, markup=False, ellipsize=False, selectable=False):
    lb = Gtk.Label(xalign=xalign)
    if markup:
        lb.set_markup(text)
    else:
        lb.set_text(text)
    for c in (cls or "").split():
        lb.add_css_class(c)
    if wrap:
        lb.set_wrap(True)
        lb.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lb.set_ellipsize(Pango.EllipsizeMode.END)
    if selectable:
        lb.set_selectable(True)
    return lb


def vbox(spacing=8, cls=None):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for c in (cls or "").split():
        b.add_css_class(c)
    return b


def hbox(spacing=8, cls=None):
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for c in (cls or "").split():
        b.add_css_class(c)
    return b


def card(title=None, sub=None):
    c = vbox(10, "card")
    if title:
        head = vbox(2)
        head.append(label(title, "card-title"))
        if sub:
            sl = label(sub, "card-sub", wrap=True)
            # ask for a modest width; it still fills a wider card. Without this a long sentence asks
            # for the whole row, and side-by-side cards stack one per row.
            sl.set_max_width_chars(40)
            head.append(sl)
        c.append(head)
    return c


def dot(color):
    d = Gtk.Box()
    d.add_css_class("dot")
    prov = Gtk.CssProvider()
    css = f"box {{ background-color: {color}; }}"
    if hasattr(prov, "load_from_string"):
        prov.load_from_string(css)
    else:
        prov.load_from_data(css.encode())
    d.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    d.set_valign(Gtk.Align.CENTER)
    return d


def tag(text, color):
    t = label(text, "tag")
    prov = Gtk.CssProvider()
    css = f"label {{ background-color: alpha({color}, 0.22); color: {color}; }}"
    if hasattr(prov, "load_from_string"):
        prov.load_from_string(css)
    else:
        prov.load_from_data(css.encode())
    t.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    t.set_valign(Gtk.Align.CENTER)
    return t


def button(text, cb, cls="pill"):
    b = Gtk.Button(label=text)
    for c in cls.split():
        b.add_css_class(c)
    b.connect("clicked", lambda *_: cb())
    return b


def run_bg(argv):
    try:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def fmt_duration(s):
    s = int(s)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    if d:
        return f"{d} d {h} h"
    if h:
        return f"{h} h {m} min"
    return f"{m} min"


# ------------------------------------------------------------------ drawing widgets
class Spark(Gtk.DrawingArea):
    """Rolling line chart."""

    def __init__(self, color, maxlen=90, height=46, maxval=None, second=None):
        super().__init__()
        self.vals, self.vals2 = [], []
        self.color = rgb(color)
        self.color2 = rgb(second) if second else None
        self.maxlen, self.maxval = maxlen, maxval
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def push(self, v, v2=None):
        self.vals = (self.vals + [v])[-self.maxlen:]
        if v2 is not None:
            self.vals2 = (self.vals2 + [v2])[-self.maxlen:]
        self.queue_draw()

    def _line(self, cr, vals, color, w, h, m):
        if len(vals) < 2:
            return
        step = w / (self.maxlen - 1)
        x0 = w - (len(vals) - 1) * step
        pts = [(x0 + i * step, h - 3 - (min(v, m) / m) * (h - 6)) for i, v in enumerate(vals)]
        cr.move_to(pts[0][0], h)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to(pts[-1][0], h)
        cr.close_path()
        g = cairo.LinearGradient(0, 0, 0, h)
        g.add_color_stop_rgba(0, *color, 0.30)
        g.add_color_stop_rgba(1, *color, 0.0)
        cr.set_source(g)
        cr.fill()
        cr.move_to(*pts[0])
        for x, y in pts[1:]:
            cr.line_to(x, y)
        cr.set_source_rgba(*color, 0.95)
        cr.set_line_width(1.8)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke()

    def _draw(self, _a, cr, w, h):
        m = self.maxval or max([1e-9] + self.vals + self.vals2) * 1.15
        if self.color2:
            self._line(cr, self.vals2, self.color2, w, h, m)
        self._line(cr, self.vals, self.color, w, h, m)


class Donut(Gtk.Overlay):
    """Ring chart split into coloured segments, with a big number in the middle.
    Changes ease in over a third of a second instead of jumping."""

    def __init__(self, size=168, ring=22):
        super().__init__()
        self.ring = ring
        self.shown, self.target = [], []
        self.area = Gtk.DrawingArea()
        self.area.set_content_width(size)
        self.area.set_content_height(size)
        self.area.set_draw_func(self._draw)
        self.set_child(self.area)
        mid = vbox(0)
        mid.set_halign(Gtk.Align.CENTER)
        mid.set_valign(Gtk.Align.CENTER)
        self.big = label("–", "donut-big", xalign=0.5)
        self.sub = label("", "small dim", xalign=0.5)
        mid.append(self.big)
        mid.append(self.sub)
        self.add_overlay(mid)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self._anim = None

    def set(self, segments, big, sub):
        """segments: [(value, "#rrggbb" or None for the empty part of the ring)]"""
        self.big.set_text(big)
        self.sub.set_text(sub)
        total = sum(v for v, _ in segments) or 1
        target = [(v / total, c) for v, c in segments]
        if [c for _, c in target] != [c for _, c in self.shown]:
            self.shown = [(0.0, c) for _, c in target]
        self.start = [v for v, _ in self.shown]
        self.target = target
        self.t0 = time.monotonic()
        if self._anim is None:
            self._anim = self.area.add_tick_callback(self._tick)

    def _tick(self, _w, _clock):
        k = min(1.0, (time.monotonic() - self.t0) / 0.35)
        k = 1 - (1 - k) ** 3
        self.shown = [(a + (b - a) * k, c) for a, (b, c) in zip(self.start, self.target)]
        self.area.queue_draw()
        if k >= 1.0:
            self._anim = None
            return False
        return True

    def _draw(self, _a, cr, w, h):
        import math
        r = min(w, h) / 2 - self.ring / 2 - 1
        cx, cy = w / 2, h / 2
        cr.set_line_width(self.ring)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_source_rgba(1, 1, 1, 0.08)
        cr.stroke()
        a = -math.pi / 2
        gap = 0.025
        for frac, color in self.shown:
            sweep = frac * 2 * math.pi
            if color and sweep > gap * 1.5:
                cr.arc(cx, cy, r, a + gap / 2, a + sweep - gap / 2)
                cr.set_source_rgba(*rgb(color), 0.95)
                cr.stroke()
            a += sweep
        # a soft highlight on the top half of the ring, like light on glass
        g = cairo.LinearGradient(0, cy - r - self.ring, 0, cy)
        g.add_color_stop_rgba(0, 1, 1, 1, 0.16)
        g.add_color_stop_rgba(1, 1, 1, 1, 0.0)
        cr.arc(cx, cy, r, math.pi, 2 * math.pi)
        cr.set_source(g)
        cr.stroke()


def legend_rows(items):
    """items: [(color, name, key)] -> (vbox of rows: dot, name, value), {key: value label}"""
    box = vbox(8)
    box.set_valign(Gtk.Align.CENTER)
    box.set_hexpand(True)
    labels = {}
    for color, name, key in items:
        r = hbox(10)
        r.append(dot(color or "rgba(255,255,255,0.18)"))
        n = label(name, "dim")
        n.set_hexpand(True)
        r.append(n)
        v = label("", "num", xalign=1.0)
        r.append(v)
        labels[key] = v
        box.append(r)
    return box, labels


class Meter(Gtk.DrawingArea):
    """Thin single-value bar (0..1)."""

    def __init__(self, color="#6aa8ff", height=6, width=-1):
        super().__init__()
        self.v = 0.0
        self.color = rgb(color)
        self.set_content_height(height)
        if width > 0:
            self.set_content_width(width)
        else:
            self.set_hexpand(True)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)

    def set(self, v, color=None):
        self.v = max(0.0, min(1.0, v))
        if color:
            self.color = rgb(color)
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        r = h / 2

        def pill(width):
            cr.new_sub_path()
            cr.arc(r, r, r, 0.5 * 3.1416, 1.5 * 3.1416)
            cr.arc(max(r, width - r), r, r, 1.5 * 3.1416, 0.5 * 3.1416)
            cr.close_path()

        pill(w)
        cr.set_source_rgba(1, 1, 1, 0.1)
        cr.fill()
        if self.v > 0:
            pill(max(h, w * self.v))
            cr.set_source_rgba(*self.color, 0.95)
            cr.fill()


# ------------------------------------------------------------------ pages
class Page(Gtk.ScrolledWindow):
    title = ""
    icon = ""

    def __init__(self, win):
        super().__init__()
        self.win = win
        # AUTOMATIC, not NEVER: with NEVER the page's widest row sets the window's minimum width,
        # and on a small screen the window then can't be made narrower than the screen.
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.body = vbox(16, "page")
        clamp = Gtk.Box()
        clamp.set_halign(Gtk.Align.FILL)
        self.body.set_hexpand(True)
        clamp.append(self.body)
        self.set_child(clamp)

    def header(self, title, sub):
        self.body.append(label(title, "page-title"))
        self.body.append(label(sub, "page-sub", wrap=True))

    def update(self, data):
        pass


class WelcomePage(Page):
    title, icon = "Welcome", "starred-symbolic"

    def __init__(self, win):
        super().__init__(win)
        hero = hbox(22)
        logo = Gtk.Image.new_from_file("/usr/share/glassos/logo.png")
        logo.set_pixel_size(112)
        hero.append(logo)
        t = vbox(6)
        t.set_valign(Gtk.Align.CENTER)
        t.append(label("Welcome to GlassOS", "hero-title"))
        t.append(label("See what's running on this computer, how much of the hardware each part uses, "
                       "and why it's there.", "hero-sub", wrap=True))
        hero.append(t)
        self.body.append(hero)

        summary = si.system_summary()
        if summary["live"]:
            live = card("You're trying GlassOS from a USB stick or DVD",
                        "Nothing on your computer has been changed. Changes you make now disappear when you "
                        "restart. The password for this live session is \"glass\".")
            row = hbox(10)
            row.append(button("Install GlassOS…", lambda: run_bg(
                ["glass-launch", "foot", "--title", "Install GlassOS", "-e", "sudo", "glass-install"]),
                "pill accent"))
            live.append(row)
            self.body.append(live)

        cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                            min_children_per_line=1, max_children_per_line=2,
                            column_spacing=16, row_spacing=16)
        c1 = card("See where your hardware goes", "Glass Lens shows every app and service, the CPU, memory, "
                  "disk and network each one uses, and every connection your computer makes.")
        c1.append(button("Open the overview", lambda: win.show_page("overview")))
        c2 = card("Make it sound like you", "Every system sound (boot, notifications, errors, plugging in a USB "
                  "stick…) comes from a sound pack. Drop in your own synth sounds.")
        c2.append(button("Choose a sound pack", lambda: win.show_page("sounds")))
        for c in (c1, c2):
            c.set_size_request(300, -1)
            cards.append(c)
        self.body.append(cards)

        keys = card("Getting around", "Super is the key with the Windows logo (⌘ on a Mac keyboard), and Alt "
                    "is Option on a Mac. Click the GlassOS logo in the top-left corner for the main menu, "
                    "or open GlassOS Help from it.")
        g = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                        min_children_per_line=1, max_children_per_line=2, column_spacing=24, row_spacing=8)
        shortcuts = [
            ("Super", "Search and open apps"), ("Super + Return", "Terminal"),
            ("Super + E", "Files"), ("Super + B", "Web browser"),
            ("Super + U", "Glass Lens"), ("Super + Q", "Close window"),
            ("Super + F", "Fullscreen"), ("Super + T", "Tile / float window"),
            ("Super + C", "Center window"), ("Super + L", "Lock screen"),
            ("Super + Alt + Backspace", "Shut down, restart or log out"), ("Super + 1…9", "Switch desktop"),
            ("Super + drag", "Move any window"), ("Drag an edge", "Resize a window"),
            ("Drag the title bar", "Move a GlassOS app's window"), ("Super + right-drag", "Resize from anywhere"),
            ("Print", "Screenshot of the whole screen"), ("Super + Shift + S", "Screenshot of an area"),
            ("3-finger swipe", "Switch desktop"), ("Super + N", "Clear notifications"),
            ("Super + /", "Show this page"),
        ]
        for k, d in shortcuts:
            r = hbox(12)
            r.set_size_request(356, -1)
            kl = label(k, "kbd")
            kl.set_halign(Gtk.Align.START)
            kl.set_valign(Gtk.Align.CENTER)
            slot = Gtk.Box()
            slot.set_size_request(196, -1)
            slot.append(kl)
            r.append(slot)
            dl = label(d, "dim", wrap=True)
            dl.set_max_width_chars(24)
            dl.set_hexpand(True)
            r.append(dl)
            g.append(r)
        keys.append(g)
        self.body.append(keys)


class OverviewPage(Page):
    title, icon = "Overview", "utilities-system-monitor-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Right now", "Where your computer's hardware is going, live. The numbers come from the "
                    "Linux kernel's own counters in /proc and /sys, so none of them are estimates.")
        grid = Gtk.Grid(column_spacing=16, row_spacing=16, column_homogeneous=True)
        self.cpu_big = label("–", "big")
        self.cpu_sub = label("", "dim small", ellipsize=True)
        self.cpu_spark = Spark(C["app"], maxval=100)
        self.mem_big = label("–", "big")
        self.mem_sub = label("", "dim small")
        self.mem_spark = Spark(C["desktop"])
        self.disk_big = label("–", "mid")
        self.disk_sub = label("", "dim small")
        self.disk_spark = Spark(C["kernel"], second=C["system"])
        self.net_big = label("–", "mid")
        self.net_sub = label("", "dim small")
        self.net_spark = Spark(C["system"], second=C["app"])
        for i, (t, big, sub, sp) in enumerate([
                ("Processor", self.cpu_big, self.cpu_sub, self.cpu_spark),
                ("Memory", self.mem_big, self.mem_sub, self.mem_spark),
                ("Disk activity", self.disk_big, self.disk_sub, self.disk_spark),
                ("Network", self.net_big, self.net_sub, self.net_spark)]):
            c = card(t)
            c.append(big)
            c.append(sub)
            c.append(sp)
            grid.attach(c, i % 2, i // 2, 1, 1)
        self.body.append(grid)

        pies = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           min_children_per_line=1, max_children_per_line=2, column_spacing=16, row_spacing=16)
        c = card("Who is using the processor", "Share of the whole CPU over the last 2 seconds.")
        row = hbox(22)
        self.cpu_pie = Donut()
        row.append(self.cpu_pie)
        lg, self.cpu_lg = legend_rows([(C["app"], "Your apps", "app"), (C["desktop"], "Desktop", "desktop"),
                                       (C["system"], "System services", "system"),
                                       (C["kernel"], "Linux kernel", "kernel"), (None, "Idle", "idle")])
        row.append(lg)
        c.append(row)
        c.set_size_request(400, -1)
        pies.append(c)

        c = card("Who is using the memory", "File cache is memory Linux borrows to speed things up "
                 "and hands back the moment an app needs it.")
        row = hbox(22)
        self.mem_pie = Donut()
        row.append(self.mem_pie)
        lg, self.mem_lg = legend_rows([(C["app"], "Your apps", "app"), (C["desktop"], "Desktop", "desktop"),
                                       (C["system"], "System services", "system"),
                                       (C["kernel"], "Linux kernel", "kernel"), (C["cache"], "File cache", "cache"),
                                       (None, "Free", "free")])
        row.append(lg)
        c.append(row)
        c.set_size_request(400, -1)
        pies.append(c)
        self.body.append(pies)

        c = card("Busiest right now", "Click Apps & Services to see everything.")
        self.top_box = vbox(0)
        c.append(self.top_box)
        self.body.append(c)

    def update(self, d):
        cpu = d["cpu"]
        self.cpu_big.set_text(f"{cpu['total']:.0f}%")
        self.cpu_sub.set_text(f"{si.NCPU} cores · {d['cpuinfo']['model']}")
        self.cpu_spark.push(cpu["total"])
        m = d["mem"]
        used = m["MemTotal"] - m["MemAvailable"]
        self.mem_big.set_text(si.human_bytes(used))
        self.mem_sub.set_text(f"in use of {si.human_bytes(m['MemTotal'])}"
                              + (f" · swap {si.human_bytes(m['SwapTotal'] - m['SwapFree'])}" if m.get("SwapTotal") else ""))
        self.mem_spark.push(used)
        rd = sum(v[0] for v in d["disk"].values())
        wr = sum(v[1] for v in d["disk"].values())
        self.disk_big.set_text(f"↓ {si.human_rate(rd)}   ↑ {si.human_rate(wr)}")
        self.disk_sub.set_text("read · write, all disks")
        self.disk_spark.push(rd, wr)
        rx = sum(v["rx_rate"] for v in d["net"].values())
        tx = sum(v["tx_rate"] for v in d["net"].values())
        self.net_big.set_text(f"↓ {si.human_rate(rx)}   ↑ {si.human_rate(tx)}")
        self.net_sub.set_text("download · upload, all connections")
        self.net_spark.push(rx, tx)

        cats = d["cpu_by_cat"]
        busy = sum(cats[k] for k in ("app", "desktop", "system", "kernel"))
        self.cpu_pie.set([(cats[k], C[k]) for k in ("app", "desktop", "system", "kernel")] + [(cats["idle"], None)],
                         f"{busy:.0f}%", "busy")
        for k, lb in self.cpu_lg.items():
            lb.set_text(f"{cats[k]:.1f}%")
        mc = d["mem_by_cat"]
        total = sum(mc[k] for k in ("app", "desktop", "system", "kernel", "cache", "free")) or 1
        inuse = sum(mc[k] for k in ("app", "desktop", "system", "kernel"))
        self.mem_pie.set([(mc[k], C[k]) for k in ("app", "desktop", "system", "kernel", "cache")] + [(mc["free"], None)],
                         f"{100 * inuse / total:.0f}%", "in use")
        for k, lb in self.mem_lg.items():
            lb.set_text(si.human_bytes(mc[k]))

        child = self.top_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.top_box.remove(child)
            child = nxt
        top = sorted(d["groups"], key=lambda g: (-round(g["cpu_pct"], 1), -g["mem"]))[:6]
        for g in top:
            r = hbox(10, "grow-row")
            r.append(dot(C[g["category"]]))
            n = label(g["name"], ellipsize=True)
            n.set_hexpand(True)
            r.append(n)
            r.append(label(f"{g['cpu_pct']:.1f}% CPU", "num small dim"))
            r.append(label(si.human_bytes(g["mem"]), "num small"))
            self.top_box.append(r)


class GroupRow(Gtk.ListBoxRow):
    def __init__(self, g):
        super().__init__()
        self.path = g["path"]
        self.g = g
        outer = vbox(4)
        row = hbox(12)
        row.set_margin_top(8)
        row.set_margin_bottom(8)
        row.append(dot(C[g["category"]]))
        names = vbox(1)
        names.set_hexpand(True)
        self.name = label(g["name"], "card-title", ellipsize=True)
        names.append(self.name)
        desc = g["explain"] or g["unit"]
        self.desc = label(desc, "dim small", wrap=True)
        names.append(self.desc)
        row.append(names)
        self.cpu = label("", "num small")
        self.cpu.set_width_chars(8)
        self.cpu.set_xalign(1)
        self.mem = label("", "num small")
        self.mem.set_width_chars(10)
        self.mem.set_xalign(1)
        self.io = label("", "num small dim")
        self.io.set_width_chars(16)
        self.io.set_xalign(1)
        for w in (self.cpu, self.mem, self.io):
            row.append(w)
        outer.append(row)
        self.rev = Gtk.Revealer()
        self.detail = vbox(2)
        self.detail.set_margin_start(24)
        self.detail.set_margin_bottom(10)
        self.rev.set_child(self.detail)
        outer.append(self.rev)
        self.set_child(outer)
        self.update(g)

    def toggle(self):
        self.rev.set_reveal_child(not self.rev.get_reveal_child())
        if self.rev.get_reveal_child():
            self.fill_detail()

    def fill_detail(self):
        child = self.detail.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.detail.remove(child)
            child = nxt
        g = self.g
        self.detail.append(label(f"Unit: {g['unit']}    cgroup: {g['path']}", "mono dim", wrap=True, selectable=True))
        self.detail.append(label(f"Memory it holds: {si.human_bytes(g['mem'])}    "
                                 f"Cached files: {si.human_bytes(g.get('cache', 0))}", "small dim"))
        for p in si.processes(g["pids"]):
            r = hbox(10)
            r.append(label(f"{p['pid']:>7}", "mono dim"))
            c = label(p["cmd"], "mono", ellipsize=True, selectable=True)
            c.set_hexpand(True)
            r.append(c)
            r.append(label(si.human_bytes(p["rss"]), "mono dim"))
            self.detail.append(r)
        if g["category"] == "app" and g["unit"].endswith(".scope"):
            b = button("Quit this app", lambda: run_bg(["systemctl", "--user", "stop", g["unit"]]), "pill")
            b.set_halign(Gtk.Align.START)
            self.detail.append(b)

    def update(self, g):
        self.g = g
        self.cpu.set_text(f"{g['cpu_pct']:.1f}%")
        self.mem.set_text(si.human_bytes(g["mem"]))
        io = g["read_rate"] + g["write_rate"]
        self.io.set_text(f"disk {si.human_rate(io)}" if io > 1024 else "")
        if self.rev.get_reveal_child():
            self.fill_detail()


class AppsPage(Page):
    title, icon = "Apps & Services", "view-app-grid-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Apps & Services", "Everything running on this computer, grouped the way Linux tracks it. "
                    "If it's running, it's listed here, with a plain-English reason. Click a row to see its "
                    "processes.")
        bar = hbox(8)
        self.filter = "all"
        first = None
        for key, name in (("all", "Everything"), ("app", "Your apps"), ("desktop", "Desktop"),
                          ("system", "System services")):
            b = Gtk.ToggleButton(label=name)
            b.add_css_class("filter")
            if first is None:
                first = b
                b.set_active(True)
            else:
                b.set_group(first)
            b.connect("toggled", self._on_filter, key)
            bar.append(b)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)
        bar.append(label("CPU · memory · disk", "dim small"))
        self.body.append(bar)
        c = card()
        self.list = Gtk.ListBox()
        self.list.add_css_class("plain")
        self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list.set_sort_func(self._sort)
        self.list.set_filter_func(self._filt)
        self.list.connect("row-activated", lambda _l, r: r.toggle())
        c.append(self.list)
        self.body.append(c)
        self.rows = {}
        self.kthreads = label("", "dim small", wrap=True)
        self.body.append(self.kthreads)

        tc = card("Scheduled tasks", "Jobs that start on their own on a timer. GlassOS keeps this list short "
                  "and turns off automatic downloads.")
        self.timer_box = vbox(4)
        tc.append(self.timer_box)
        self.body.append(tc)
        self.timers_loaded = 0

    def _on_filter(self, btn, key):
        if btn.get_active():
            self.filter = key
            self.list.invalidate_filter()

    def _filt(self, row):
        return self.filter == "all" or row.g["category"] == self.filter

    @staticmethod
    def _sort(a, b):
        ka = (-round(a.g["cpu_pct"], 1), -a.g["mem"])
        kb = (-round(b.g["cpu_pct"], 1), -b.g["mem"])
        return -1 if ka < kb else (1 if ka > kb else 0)

    def update(self, d):
        seen = set()
        for g in d["groups"]:
            seen.add(g["path"])
            if g["path"] in self.rows:
                self.rows[g["path"]].update(g)
            else:
                r = GroupRow(g)
                self.rows[g["path"]] = r
                self.list.append(r)
        for p in list(self.rows):
            if p not in seen:
                self.list.remove(self.rows.pop(p))
        self.list.invalidate_sort()
        self.kthreads.set_text(f"Plus {si.kernel_threads()} Linux kernel threads (drivers, file systems, "
                               "memory management). Their CPU time is shown as \"Linux kernel\" on the overview.")
        if time.monotonic() - self.timers_loaded > 30:
            self.timers_loaded = time.monotonic()
            child = self.timer_box.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                self.timer_box.remove(child)
                child = nxt
            for t in si.timers():
                r = hbox(10, "grow-row")
                n = vbox(1)
                n.set_hexpand(True)
                n.append(label(t["unit"] + ("  (yours)" if t["user"] else ""), "small"))
                n.append(label(t["explain"] or f"Runs {t['activates']}", "dim small", wrap=True))
                r.append(n)
                nxt = t.get("next")
                when = "not scheduled"
                if nxt:
                    secs = nxt / 1e6 - time.time()
                    when = "in " + fmt_duration(secs) if secs > 0 else "now"
                r.append(label(when, "dim small num"))
                self.timer_box.append(r)


class NetworkPage(Page):
    title, icon = "Network & Privacy", "network-wireless-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Network & Privacy", "Every connection this computer has open right now, what is allowed in, "
                    "and how GlassOS itself is set up on the network.")
        pc = card("How GlassOS is set up")
        self.fw = label("", "small")
        facts = [
            ("Usage data", "GlassOS doesn't include a telemetry or crash-report service. "
                           "Apps & Services lists everything that's running."),
            ("Connectivity check", "Switched off in NetworkManager, so joining a network doesn't contact a test server."),
            ("Updates", "Downloaded only when you open GlassOS menu > Software Updates. "
                        "Debian's automatic update timers are turned off."),
            ("Wi-Fi hardware address", "Randomized while scanning, and a different one is used for each network."),
            ("Firefox", "Telemetry, studies, sponsored content and Pocket are switched off by policy. "
                        "Strict tracking protection is on, and search uses DuckDuckGo."),
            ("Clock sync", "systemd-timesyncd gets the time from Debian's public time servers. "
                           "Secure websites need an accurate clock."),
        ]
        g = Gtk.Grid(column_spacing=10, row_spacing=8)
        fwrow = hbox(8)
        self.fw_icon = label("✓", "check")
        fwrow.append(self.fw_icon)
        g.attach(self.fw_icon, 0, 0, 1, 1)
        fwl = vbox(1)
        fwl.append(label("Firewall", "small"))
        fwl.append(self.fw)
        g.attach(fwl, 1, 0, 1, 1)
        for i, (t, desc) in enumerate(facts, start=1):
            g.attach(label("✓", "check"), 0, i, 1, 1)
            b = vbox(1)
            b.append(label(t, "small"))
            b.append(label(desc, "dim small", wrap=True))
            g.attach(b, 1, i, 1, 1)
        pc.append(g)
        self.body.append(pc)

        ic = card("Connections", "Network adapters and how much data they move.")
        self.iface_box = vbox(6)
        ic.append(self.iface_box)
        self.spark = Spark(C["system"], second=C["app"], height=54)
        ic.append(self.spark)
        self.body.append(ic)

        cc = card("Who's talking to the internet right now",
                  "Each open connection, the program that made it and where it goes. Addresses are not looked "
                  "up online (that would itself leak where you browse).")
        self.conn_box = vbox(0)
        cc.append(self.conn_box)
        self.body.append(cc)

        lc = card("Open to the network", "Programs waiting for incoming connections. The firewall blocks "
                  "these from outside unless you open a port.")
        self.listen_box = vbox(0)
        lc.append(self.listen_box)
        self.body.append(lc)

        ac = card("Data used by system services since boot",
                  "Measured per service by systemd (IP accounting). \"user-1000.slice\" is all of your own apps combined.")
        self.acct_box = vbox(0)
        ac.append(self.acct_box)
        self.body.append(ac)
        self.acct_t = 0

    @staticmethod
    def _clear(box):
        child = box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    def update(self, d):
        self._clear(self.iface_box)
        rx = tx = 0
        for name, v in d["net"].items():
            rx += v["rx_rate"]
            tx += v["tx_rate"]
            r = hbox(10)
            r.append(label(f"{v['kind']} ({name})", "small"))
            r.append(label(v["addr"] or "not connected", "dim small mono"))
            s = Gtk.Box()
            s.set_hexpand(True)
            r.append(s)
            r.append(label(f"↓ {si.human_rate(v['rx_rate'])}  ↑ {si.human_rate(v['tx_rate'])}", "num small"))
            r.append(label(f"since boot ↓ {si.human_bytes(v['rx_total'])} ↑ {si.human_bytes(v['tx_total'])}",
                           "num small dim"))
            self.iface_box.append(r)
        self.spark.push(rx, tx)

        conns, listening = si.connections()
        self._clear(self.conn_box)
        if not conns:
            self.conn_box.append(label("No open connections.", "dim small"))
        for c in sorted(conns, key=lambda c: c["process"])[:80]:
            r = hbox(10, "grow-row")
            p = label(c["process"], "small")
            p.set_width_chars(18)
            p.set_ellipsize(Pango.EllipsizeMode.END)
            r.append(p)
            r.append(label(c["proto"].upper(), "dim small mono"))
            dest = label(f"{c['rhost']}:{c['rport']}", "mono", ellipsize=True, selectable=True)
            dest.set_hexpand(True)
            r.append(dest)
            r.append(label(c.get("service", ""), "dim small"))
            r.append(label(c["state"].lower(), "dim small"))
            self.conn_box.append(r)
        self._clear(self.listen_box)
        exposed = [x for x in listening if x.get("exposed")]
        if not exposed:
            self.listen_box.append(label("Nothing is listening on the network. ", "dim small"))
        for x in exposed:
            r = hbox(10, "grow-row")
            r.append(label(x["process"], "small"))
            r.append(label(f"{x['proto'].upper()} port {x['lport']}", "mono dim"))
            s = Gtk.Box()
            s.set_hexpand(True)
            r.append(s)
            try:
                r.append(label(si.PORTS.get(int(x["lport"]), ""), "dim small"))
            except ValueError:
                pass
            self.listen_box.append(r)

        # these two start programs (systemctl), so they refresh every 8 seconds, not every tick
        if time.monotonic() - self.acct_t > 8:
            self.acct_t = time.monotonic()
            fw = si.firewall_status()
            self.fw.set_text("On: incoming connections are blocked, everything you start can connect out."
                             if fw else "Off: incoming connections are not filtered.")
            self.fw.add_css_class("dim")
            self.fw_icon.set_text("✓" if fw else "!")
            acct = si.ip_accounting()
            self._clear(self.acct_box)
            if not acct:
                self.acct_box.append(label("No per-service network data yet.", "dim small"))
            for unit, v in sorted(acct.items(), key=lambda kv: -(kv[1]["in"] + kv[1]["out"]))[:15]:
                r = hbox(10, "grow-row")
                n = vbox(1)
                n.set_hexpand(True)
                n.append(label(unit, "small"))
                n.append(label(si.explain(unit) or v["desc"], "dim small", wrap=True))
                r.append(n)
                r.append(label(f"↓ {si.human_bytes(v['in'])}  ↑ {si.human_bytes(v['out'])}", "num small"))
                self.acct_box.append(r)


class HardwarePage(Page):
    title, icon = "Hardware", "computer-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Hardware", "What's inside this computer and how hard each part is working.")
        s = si.system_summary()
        ci = si.cpu_info()
        m = si.meminfo()
        c = card("This computer")
        g = Gtk.Grid(column_spacing=24, row_spacing=6)
        rows = [("Model", s["product"] or "Unknown"), ("Processor", f"{ci['model']} ({si.NCPU} cores, {ci['arch']})"),
                ("Memory", si.human_bytes(m["MemTotal"])), ("Startup mode", s["boot"]),
                ("Linux kernel", s["kernel"]), ("Running for", "")]
        self.uptime = None
        for i, (k, v) in enumerate(rows):
            g.attach(label(k, "dim small"), 0, i, 1, 1)
            lb = label(v, "small", selectable=True)
            g.attach(lb, 1, i, 1, 1)
            if k == "Running for":
                self.uptime = lb
        c.append(g)
        self.body.append(c)

        cc = card("Processor cores", "How busy each core is, and its current speed.")
        self.cores = []
        cg = Gtk.Grid(column_spacing=12, row_spacing=6)
        for i in range(si.NCPU):
            cg.attach(label(f"Core {i}", "dim small"), 0, i, 1, 1)
            mt = Meter(C["app"])
            cg.attach(mt, 1, i, 1, 1)
            pl = label("", "num small")
            pl.set_width_chars(5)
            pl.set_xalign(1)
            cg.attach(pl, 2, i, 1, 1)
            fl = label("", "num small dim")
            fl.set_width_chars(9)
            fl.set_xalign(1)
            cg.attach(fl, 3, i, 1, 1)
            self.cores.append((mt, pl, fl))
        cc.append(cg)
        self.body.append(cc)

        self.gpu_card = card("Graphics")
        self.gpu_box = vbox(6)
        self.gpu_card.append(self.gpu_box)
        self.body.append(self.gpu_card)

        self.sto = card("Storage")
        self.sto_box = vbox(8)
        self.sto.append(self.sto_box)
        self.body.append(self.sto)

        self.temp_card = card("Temperatures")
        self.temp_box = vbox(4)
        self.temp_card.append(self.temp_box)
        self.body.append(self.temp_card)

        self.bat_card = card("Battery")
        self.bat_box = vbox(4)
        self.bat_card.append(self.bat_box)
        self.body.append(self.bat_card)
        self.slow_t = 0.0

    def update(self, d):
        if self.uptime:
            self.uptime.set_text(fmt_duration(si.uptime()))
        freqs = si.core_freqs()
        for i, (mt, pl, fl) in enumerate(self.cores):
            v = d["cpu"]["cores"][i] if i < len(d["cpu"]["cores"]) else 0
            mt.set(v / 100, C["kernel"] if v > 80 else C["app"])
            pl.set_text(f"{v:.0f}%")
            f = freqs[i] if i < len(freqs) else None
            fl.set_text(f"{f / 1000:.2f} GHz" if f else "")
        # Graphics, storage, temperatures and battery change slowly, and reading some sensors wakes
        # the drive or the embedded controller, so they refresh every 10 seconds
        if time.monotonic() - self.slow_t < 10:
            return
        self.slow_t = time.monotonic()
        NetworkPage._clear(self.gpu_box)
        gl = si.gpus()
        if not gl:
            self.gpu_box.append(label("No graphics device found.", "dim small"))
        for g in gl:
            r = hbox(10)
            r.append(label(g["name"], "small"))
            r.append(label(f"driver: {g['driver']}", "dim small mono"))
            s = Gtk.Box()
            s.set_hexpand(True)
            r.append(s)
            if g["busy"] is not None:
                r.append(label(f"{g['busy']}% busy", "num small"))
            else:
                r.append(label("this driver doesn't report how busy it is", "dim small"))
            if g["vram_total"]:
                r.append(label(f"VRAM {si.human_bytes(g['vram_used'])} / {si.human_bytes(g['vram_total'])}", "num small dim"))
            self.gpu_box.append(r)
        NetworkPage._clear(self.sto_box)
        for dk in si.disks():
            rr, ww = d["disk"].get(dk["name"], (0, 0))
            r = hbox(10)
            r.append(label(f"{dk['kind']} · {dk['model'] or dk['name']}", "small"))
            r.append(label(si.human_bytes(dk["size"]), "dim small"))
            s = Gtk.Box()
            s.set_hexpand(True)
            r.append(s)
            r.append(label(f"↓ {si.human_rate(rr)}  ↑ {si.human_rate(ww)}", "num small dim"))
            self.sto_box.append(r)
        for mnt in si.mounts():
            r = hbox(10)
            lb = label(mnt["label"], "small")
            lb.set_width_chars(18)
            r.append(lb)
            mt = Meter(C["desktop"], height=8)
            mt.set(mnt["used"] / mnt["total"])
            r.append(mt)
            r.append(label(f"{si.human_bytes(mnt['used'])} of {si.human_bytes(mnt['total'])}", "num small dim"))
            self.sto_box.append(r)
        NetworkPage._clear(self.temp_box)
        temps = si.temperatures()
        self.temp_card.set_visible(bool(temps))
        for t in temps[:12]:
            r = hbox(10)
            r.append(label(f"{t['sensor']} · {t['label']}", "small"))
            s = Gtk.Box()
            s.set_hexpand(True)
            r.append(s)
            cls = "bad" if t["c"] > 85 else ("warn" if t["c"] > 70 else "num")
            r.append(label(f"{t['c']:.0f} °C", "small " + cls))
            self.temp_box.append(r)
        NetworkPage._clear(self.bat_box)
        bats = si.batteries()
        self.bat_card.set_visible(bool(bats))
        for b in bats:
            r = hbox(10)
            r.append(label(f"{b['capacity']}% · {b['status']}", "small"))
            if b["watts"]:
                r.append(label(f"{b['watts']:.1f} W", "num small dim"))
            if b["health"]:
                r.append(label(f"health {b['health']:.0f}% of original capacity", "dim small"))
            self.bat_box.append(r)


class SoundsPage(Page):
    title, icon = "Sounds", "audio-speakers-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Sounds", "Every sound GlassOS makes comes from a sound pack: a folder of audio files "
                    "named after events. Make your own and drop it in.")
        top = card()
        r = hbox(12)
        r.append(label("System sounds", "card-title"))
        self.enabled = Gtk.Switch()
        self.enabled.set_valign(Gtk.Align.CENTER)
        r.append(self.enabled)
        s = Gtk.Box()
        s.set_hexpand(True)
        r.append(s)
        r.append(label("Volume", "dim small"))
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol.set_draw_value(False)
        self.vol.set_size_request(220, -1)
        r.append(self.vol)
        top.append(r)
        r2 = hbox(12)
        r2.append(label("Sound pack", "dim small"))
        self.dd = Gtk.DropDown.new_from_strings([])
        r2.append(self.dd)
        self.pack_info = label("", "dim small", wrap=True)
        self.pack_info.set_hexpand(True)
        r2.append(self.pack_info)
        top.append(r2)
        r3 = hbox(8)
        r3.append(button("Import a pack folder…", self.import_pack))
        r3.append(button("Open my packs folder", self.open_packs))
        self.new_name = Gtk.Entry()
        self.new_name.set_placeholder_text("New pack name")
        r3.append(self.new_name)
        r3.append(button("Create starter pack", self.new_pack))
        top.append(r3)
        self.msg = label("", "small dim", wrap=True)
        top.append(self.msg)
        self.body.append(top)

        ec = card("Events", "▶ plays the sound. Untick to silence just that event. Files can be WAV, OGG, FLAC, "
                  "MP3 or Opus, named exactly like the event (for example boot.wav).")
        self.ev_box = vbox(0)
        ec.append(self.ev_box)
        self.body.append(ec)
        self.loading = True
        self.reload()
        self.enabled.connect("notify::active", self.on_enabled)
        self.vol.connect("value-changed", self.on_volume)
        self.dd.connect("notify::selected", self.on_pack)
        self.loading = False
        self._save_id = None

    def reload(self):
        self.loading = True
        self.settings = gs.Settings()
        self.packs = gs.all_packs()
        self.ids = list(self.packs)
        model = Gtk.StringList.new([f"{p.name}" + ("  (yours)" if p.user else "") for p in self.packs.values()])
        self.dd.set_model(model)
        if self.settings.pack in self.ids:
            self.dd.set_selected(self.ids.index(self.settings.pack))
        self.enabled.set_active(self.settings.enabled)
        self.vol.set_value(self.settings.volume * 100)
        p = self.packs.get(self.settings.pack)
        if p:
            self.pack_info.set_text(" · ".join(x for x in (p.author and f"by {p.author}", p.description) if x))
        NetworkPage._clear(self.ev_box)
        unmuted = self._unmuted_settings()
        for ev, (desc, _fb, _fd) in gs.EVENTS.items():
            f, _v = gs.resolve(ev, unmuted, self.packs)
            r = hbox(10, "grow-row")
            cb = Gtk.CheckButton()
            cb.set_active(ev not in self.settings.mute)
            cb.connect("toggled", self.on_mute, ev)
            r.append(cb)
            n = vbox(1)
            n.set_hexpand(True)
            n.append(label(ev, "mono"))
            n.append(label(desc, "dim small"))
            r.append(n)
            src = "silent (no file in this pack)"
            if f:
                pack_dir = os.path.basename(os.path.dirname(f))
                src = os.path.basename(f) + ("" if pack_dir == self.settings.pack else f"  from {pack_dir}")
            r.append(label(src, "dim small mono"))
            pb = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
            pb.add_css_class("flat-icon")
            pb.set_sensitive(bool(f))
            pb.connect("clicked", lambda _b, path=f: path and gs.play_file(path, max(0.2, self.settings.volume)))
            r.append(pb)
            self.ev_box.append(r)
        self.loading = False

    def _unmuted_settings(self):
        s = gs.Settings()
        s.mute = set()
        s.enabled = True
        return s

    def _save(self):
        self.settings.save()
        self._save_id = None
        return False

    def on_enabled(self, sw, _p):
        if self.loading:
            return
        self.settings.enabled = sw.get_active()
        self._save()

    def on_volume(self, sc):
        if self.loading:
            return
        self.settings.volume = sc.get_value() / 100
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(400, self._save)

    def on_mute(self, cb, ev):
        if self.loading:
            return
        (self.settings.mute.discard if cb.get_active() else self.settings.mute.add)(ev)
        self._save()
        gs.build_sound_theme()

    def on_pack(self, dd, _p):
        if self.loading:
            return
        i = dd.get_selected()
        if 0 <= i < len(self.ids):
            pid = self.ids[i]
            r = subprocess.run(["glass-soundpack", "use", pid], capture_output=True, text=True)
            self.msg.set_text(r.stdout.strip() or r.stderr.strip())
            gs.play("login")
            GLib.idle_add(self.reload)

    def import_pack(self):
        dlg = Gtk.FileDialog(title="Choose a sound pack folder")

        def done(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            r = subprocess.run(["glass-soundpack", "install", folder.get_path()], capture_output=True, text=True)
            self.msg.set_text((r.stdout + r.stderr).strip())
            self.reload()

        dlg.select_folder(self.win, None, done)

    def open_packs(self):
        os.makedirs(gs.USER_PACKS, exist_ok=True)
        run_bg(["xdg-open", gs.USER_PACKS])

    def new_pack(self):
        name = self.new_name.get_text().strip() or "My Sounds"
        r = subprocess.run(["glass-soundpack", "new", name], capture_output=True, text=True)
        self.msg.set_text((r.stdout + r.stderr).strip())
        out = r.stdout.split("\n")[0].replace("Created ", "").strip()
        if os.path.isdir(out):
            run_bg(["xdg-open", out])


class AboutPage(Page):
    title, icon = "About GlassOS", "help-about-symbolic"

    def __init__(self, win):
        super().__init__(win)
        s = si.system_summary()
        b = s["build"]
        hero = hbox(20)
        logo = Gtk.Image.new_from_file("/usr/share/glassos/logo.png")
        logo.set_pixel_size(96)
        hero.append(logo)
        t = vbox(4)
        t.set_valign(Gtk.Align.CENTER)
        t.append(label(f"GlassOS {b.get('GLASSOS_VERSION', '')} “{b.get('GLASSOS_CODENAME', '')}”", "hero-title"))
        t.append(label(f"Built on Debian {s['debian']} · Linux {s['kernel']} · Hyprland {s['hyprland']} · "
                       f"{s['arch']} · built {b.get('BUILD_DATE', '')[:10]}", "dim", wrap=True))
        hero.append(t)
        self.body.append(hero)
        row = hbox(8)
        row.append(button("Check for updates…", lambda: run_bg(
            ["glass-launch", "foot", "--title", "Software Updates", "-e", "glass-update"]), "pill accent"))
        row.append(button("Open the terminal", lambda: run_bg(["glass-launch", "foot"])))
        self.body.append(row)

        pc = card("How GlassOS is built")
        for t_, d_ in [
            ("Visible", "Glass Lens lists every running app and service with the reason it exists, and every "
                        "package GlassOS ships is listed below with the reason it's included."),
            ("Usage data", "There's no telemetry, analytics or crash-upload software installed, and no online "
                           "account to sign in to."),
            ("Updates", "Nothing installs or restarts by itself. Updates run when you start them."),
            ("Small", "Debian's optional \"recommended\" packages are left out. Add any app you want with apt."),
            ("Open source", "Every package comes from Debian's free and open-source archive. The build scripts "
                            "are plain text you can read and change."),
            ("Your files", "Themes, sounds and settings are plain files in your home folder."),
        ]:
            r = hbox(10)
            v = vbox(1)
            v.append(label(t_, "small"))
            v.append(label(d_, "dim small", wrap=True))
            r.append(v)
            pc.append(r)
        self.body.append(pc)

        n, size = si.package_stats()
        mc = card("Everything that's installed, and why",
                  f"{n} packages in total ({si.human_bytes(size)}). These are the ones GlassOS chose on purpose; "
                  "the rest are the libraries they need. Source: /usr/share/glassos/packages.list")
        for sec, pkgs in si.manifest():
            ex = Gtk.Expander(label=f"{sec}  ({len(pkgs)})")
            box = vbox(2)
            box.set_margin_start(12)
            for name, why in pkgs:
                r = hbox(10)
                pl = label(name, "mono")
                pl.set_width_chars(26)
                r.append(pl)
                r.append(label(why, "dim small", wrap=True))
                box.append(r)
            ex.set_child(box)
            mc.append(ex)
        self.body.append(mc)

        lc = card("Credits & licenses", "GlassOS is put together from open-source projects: "
                  "the Linux kernel, Debian, Hyprland, GTK, PipeWire, Mesa, Firefox and many more. Each package's "
                  "license is in /usr/share/doc/<package>/copyright. Fonts: Inter and JetBrains Mono (SIL OFL). "
                  "Icons: Papirus (GPL-3). The GlassOS look, logo, wallpapers and sounds are original.")
        self.body.append(lc)


PAGES = [("welcome", WelcomePage), ("overview", OverviewPage), ("apps", AppsPage), ("network", NetworkPage),
         ("hardware", HardwarePage), ("sounds", SoundsPage), ("about", AboutPage)]


# ------------------------------------------------------------------ window
class LensWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Glass Lens")
        self.add_css_class("glass")
        self.add_css_class("lens")
        glassui.fit_size(self, 1120, 760)
        hb = Gtk.HeaderBar()
        hb.set_title_widget(label("Glass Lens", "title"))
        self.set_titlebar(hb)
        glassui.drag_by_titlebar(self, hb)

        self.cpu = si.CpuSampler()
        self.groups = si.GroupSampler()
        self.disk = si.DiskSampler()
        self.net = si.NetSampler()
        self.cpuinfo = si.cpu_info()
        self.cpu.sample()
        self.groups.sample()
        self.disk.sample()
        self.net.sample()

        root = hbox(0)
        side = vbox(0, "sidebar-pane")
        side.set_size_request(220, -1)
        brand = hbox(8)
        brand.set_margin_top(6)
        lg = Gtk.Image.new_from_file("/usr/share/icons/hicolor/32x32/apps/glass-lens.png")
        lg.set_pixel_size(22)
        brand.append(lg)
        brand.append(label("Glass Lens", "brand"))
        brand.set_margin_start(14)
        side.append(brand)
        self.sidebar = Gtk.ListBox()
        self.sidebar.set_selection_mode(Gtk.SelectionMode.SINGLE)
        side.append(self.sidebar)
        root.append(side)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        root.append(self.stack)
        self.set_child(root)

        self.pages = {}
        self.rows = {}
        for key, cls in PAGES:
            try:
                page = cls(self)
            except Exception as e:  # a broken page must never take the whole app down
                page = Page(self)
                page.header(cls.title, f"This page failed to load: {e}")
                page.title, page.icon = cls.title, cls.icon
            self.pages[key] = page
            self.stack.add_named(page, key)
            row = Gtk.ListBoxRow()
            rb = hbox(10)
            ic = Gtk.Image.new_from_icon_name(cls.icon)
            rb.append(ic)
            rb.append(label(cls.title))
            row.set_child(rb)
            row.key = key
            self.rows[key] = row
            self.sidebar.append(row)
        self.sidebar.connect("row-selected", self.on_row)
        self.show_page("overview")
        self.tick()
        GLib.timeout_add(REFRESH_MS, self.tick)

    def show_page(self, key):
        if key not in self.pages:
            key = "overview"
        self.stack.set_visible_child_name(key)
        self.sidebar.select_row(self.rows[key])
        GLib.idle_add(self.refresh_now)

    def on_row(self, _lb, row):
        if row:
            self.stack.set_visible_child_name(row.key)
            GLib.idle_add(self.refresh_now)

    def refresh_now(self):
        # Fill a page as soon as it's opened. Returning False matters: tick() returns True to keep
        # its 2-second timer going, and an idle callback returning True runs nonstop.
        self.tick()
        return False

    def collect(self):
        cpu = self.cpu.sample()
        groups, _top, _dt = self.groups.sample()
        mem = si.meminfo()
        by_cat = {"app": 0.0, "desktop": 0.0, "system": 0.0}
        mem_cat = {"app": 0, "desktop": 0, "system": 0}
        for g in groups:
            by_cat[g["category"]] = by_cat.get(g["category"], 0) + g["cpu_pct"]
            mem_cat[g["category"]] = mem_cat.get(g["category"], 0) + g["mem"]
        total = cpu["total"]
        attributed = sum(by_cat.values())
        if attributed > total:  # timing jitter between the two sources
            scale = total / attributed if attributed else 0
            for k in by_cat:
                by_cat[k] *= scale
        by_cat["kernel"] = max(0.0, total - sum(by_cat.values()))
        by_cat["idle"] = max(0.0, 100 - total)
        kern = mem.get("SUnreclaim", 0) + mem.get("KernelStack", 0) + mem.get("PageTables", 0)
        mem_cat["kernel"] = kern
        mem_cat["free"] = mem.get("MemFree", 0)
        used_known = sum(mem_cat[k] for k in ("app", "desktop", "system", "kernel"))
        mem_cat["cache"] = max(0, mem["MemTotal"] - mem_cat["free"] - used_known)
        return {"cpu": cpu, "groups": groups, "mem": mem, "cpu_by_cat": by_cat, "mem_by_cat": mem_cat,
                "disk": self.disk.sample(), "net": self.net.sample(), "cpuinfo": self.cpuinfo}

    def tick(self):
        try:
            data = self.collect()
        except Exception as e:
            print("glass-lens: sample failed:", e, file=sys.stderr)
            return True
        # the overview's charts keep their history even while you look at another page
        self.pages["overview"].update(data)
        cur = self.stack.get_visible_child_name()
        if cur not in ("overview", "welcome", "sounds", "about"):
            try:
                self.pages[cur].update(data)
            except Exception as e:
                print(f"glass-lens: {cur} update failed:", e, file=sys.stderr)
        return True


class LensApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()
        page = None
        if "--page" in args and args.index("--page") + 1 < len(args):
            page = args[args.index("--page") + 1]
        if self.win is None:
            prov = Gtk.CssProvider()
            if hasattr(prov, "load_from_string"):
                prov.load_from_string(CSS)
            else:
                prov.load_from_data(CSS.encode())
            glassui.apply_css()
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.win = LensWindow(self)
        if page:
            self.win.show_page(page)
        self.win.present()
        return 0


if __name__ == "__main__":
    sys.exit(LensApp().run(sys.argv))
