"""Shared look for GlassOS's own apps ("Prism" glass).

Every GlassOS window is see-through: its background is a translucent tint and Hyprland blurs
whatever is behind it - including other windows. So one window over the wallpaper looks lightly
frosted, and each extra window stacked on top adds another layer of frost and tint, the way
real panes of glass do.

How glassy it is comes from one setting, Settings > Appearance > Glass, a slider from Clear to
Frosted (like macOS Golden Gate's Liquid Glass slider). It is stored in
~/.config/glassos/appearance.json as "glass" (0 = Clear, 100 = Frosted), and glass_look() turns it
into everything it moves: the tint, and the blur Hyprland draws.

Clear: a light blur, so shapes behind stay recognisable; little tint, so the wallpaper keeps its
colour; a bright rim with a darker band just inside it, so the pane still reads as a sheet of glass.
Frosted: a heavy blur and a milky slate tint, so nothing behind competes with the text.
"""
import json
import os
import socket
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "glassos")
APPEARANCE = os.path.join(CONF, "appearance.json")
DEFAULTS = {"glass": 35, "accent": "#6aa8ff"}

# Tint colour at each end of the slider: smoky and dark when clear, a lighter milky slate when frosted
CLEAR_TINT = (14, 16, 24)
FROSTED_TINT = (42, 44, 58)


def glass_look(level):
    """Everything the Glass slider moves, from its value (0 = Clear, 100 = Frosted)."""
    g = max(0.0, min(1.0, float(level) / 100))

    def lerp(a, b):
        return a + (b - a) * g

    rgb = tuple(round(lerp(c, f)) for c, f in zip(CLEAR_TINT, FROSTED_TINT))
    return {
        # GlassOS windows
        "tint": round(lerp(0.28, 0.72), 2),            # how much of the window is tint, not backdrop
        "tint_rgb": "#%02x%02x%02x" % rgb,
        "fill": round(lerp(0.05, 0.09), 3),            # cards and panels on the glass
        "halo": round(lerp(0.45, 0.0), 2),             # soft shadow behind white text, for clear glass
        # Hyprland's blur (Settings writes these to glass-settings.lua)
        "frost_size": round(lerp(3, 10)),
        "frost_passes": 2 if g < 0.67 else 3,
        "frost_vibrancy": round(lerp(0.75, 0.30), 2),  # clear glass keeps the wallpaper's colour
        "frost_brightness": round(lerp(0.70, 0.62), 2),
        "frost_noise": round(lerp(0.006, 0.022), 3),   # frosted glass has a fine grain
    }


def appearance():
    a = dict(DEFAULTS)
    saved = {}
    try:
        with open(APPEARANCE) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        pass
    if isinstance(saved, dict):
        a.update(saved)
        if "glass" not in saved and "tint" in saved:
            # saved before the Glass slider existed: map the old Tint setting onto it
            try:
                a["glass"] = (float(saved["tint"]) - 0.28) / 0.44 * 100
            except (TypeError, ValueError):
                pass
    try:
        a["glass"] = max(0, min(100, round(float(a["glass"]))))
    except (TypeError, ValueError):
        a["glass"] = DEFAULTS["glass"]
    a["tint"] = glass_look(a["glass"])["tint"]
    return a


def save_appearance(**changes):
    a = appearance()
    a.update(changes)
    os.makedirs(CONF, exist_ok=True)
    tmp = APPEARANCE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(a, f, indent=2)
    os.replace(tmp, APPEARANCE)
    return a


# A sheet of glass, as in macOS Golden Gate: light catches the top edge (and, more faintly, the
# bottom one, where it comes back out), and a darker band sits just inside the rim.
def glass_edges(top=0.30, bottom=0.12, side=0.10, sheen=0.12, edge=0.16):
    return (f"border: 1px solid alpha(#ffffff, {side}); border-top-color: alpha(#ffffff, {top}); "
            f"border-bottom-color: alpha(#ffffff, {bottom}); "
            f"box-shadow: inset 0 1px 1px alpha(#ffffff, {sheen}), inset 0 -1px 1px alpha(#ffffff, {sheen / 3:.3f}), "
            f"inset 0 0 0 1px alpha(#000000, {edge});")


def base_css():
    a = appearance()
    look = glass_look(a["glass"])
    t, tint, fill, halo = look["tint"], look["tint_rgb"], look["fill"], look["halo"]
    acc = a["accent"]
    pill = glass_edges(top=0.34, bottom=0.14, side=0.14, sheen=0.16, edge=0.12)
    return f"""
window.glass {{ background-color: alpha({tint}, {t:.2f}); color: #f4f5fa;
  background-image: linear-gradient(180deg, alpha(#ffffff, 0.045), alpha(#ffffff, 0) 140px); }}
window.glass.solid {{ background-color: alpha({tint}, {min(0.95, t + 0.35):.2f}); }}
window.glass label {{ text-shadow: 0 0 3px alpha(#000000, {halo}); }}
window.glass headerbar {{ background: transparent; box-shadow: none; border: none; min-height: 42px; color: #fff; }}
window.glass headerbar windowcontrols button {{ min-width: 14px; min-height: 14px; padding: 0; margin: 0 3px; }}
.glass-panel {{
  background-image: linear-gradient(180deg, alpha(#ffffff, {fill + 0.03:.3f}), alpha(#ffffff, {fill:.3f}));
  border-radius: 18px;
  {glass_edges()}
}}
.glass-pane {{ background: alpha(#ffffff, {fill * 0.6:.3f}); }}
.sidebar-pane {{ background: alpha(#ffffff, {fill * 0.7:.3f}); border-right: 1px solid alpha(#ffffff, 0.07); }}
.sidebar-pane list {{ background: transparent; }}
.sidebar-pane row {{ padding: 8px 12px; margin: 2px 10px; border-radius: 11px; color: alpha(#ffffff, 0.86); }}
.sidebar-pane row:selected {{ background-image: linear-gradient(180deg, alpha(#ffffff, 0.19), alpha(#ffffff, 0.12));
  color: #fff; box-shadow: inset 0 1px alpha(#ffffff, 0.22), inset 0 -1px alpha(#ffffff, 0.05); }}
.sidebar-pane row:hover:not(:selected) {{ background: alpha(#ffffff, 0.06); }}
.page {{ padding: 24px 30px 36px 30px; }}
.page-title {{ font-size: 26px; font-weight: 800; }}
.page-sub {{ color: alpha(#ffffff, 0.86); }}
.card {{ background-image: linear-gradient(180deg, alpha(#ffffff, {fill + 0.025:.3f}), alpha(#ffffff, {fill:.3f}));
        border-radius: 16px; padding: 14px 16px;
        {glass_edges(top=0.26, bottom=0.10, side=0.08, sheen=0.10, edge=0.14)} }}
.card-title {{ font-weight: 700; }}
.dim {{ color: alpha(#ffffff, 0.85); }}
.small {{ font-size: 12px; }}
.mono {{ font-family: "JetBrains Mono", monospace; font-size: 12px; }}
.row {{ padding: 8px 2px; border-bottom: 1px solid alpha(#ffffff, 0.06); }}
.ok {{ color: #5fe3a1; }}
.warn {{ color: #ffd479; }}
button.pill {{ border-radius: 99px; padding: 6px 16px; color: #fff;
              background-image: linear-gradient(180deg, alpha(#ffffff, 0.17), alpha(#ffffff, 0.09));
              {pill} }}
button.pill:hover {{ background-image: linear-gradient(180deg, alpha(#ffffff, 0.25), alpha(#ffffff, 0.15)); }}
button.pill:active {{ background-image: linear-gradient(180deg, alpha(#ffffff, 0.10), alpha(#ffffff, 0.16)); }}
button.accent {{ background-image: linear-gradient(180deg, alpha({acc}, 0.78), alpha({acc}, 0.56));
                border-color: alpha(#ffffff, 0.24); border-top-color: alpha(#ffffff, 0.48); }}
button.accent:hover {{ background-image: linear-gradient(180deg, alpha({acc}, 0.92), alpha({acc}, 0.72)); }}
button.round {{ border-radius: 99px; min-width: 32px; min-height: 32px; padding: 0; color: #fff;
               background-image: linear-gradient(180deg, alpha(#ffffff, 0.13), alpha(#ffffff, 0.06));
               {pill} }}
button.round:hover {{ background-image: linear-gradient(180deg, alpha(#ffffff, 0.24), alpha(#ffffff, 0.14)); }}
button.round:disabled {{ opacity: 0.35; }}
entry.glass-entry, entry {{ background: alpha(#000000, 0.14); border: 1px solid alpha(#ffffff, 0.12);
                          border-bottom-color: alpha(#ffffff, 0.22);
                          box-shadow: inset 0 1px 2px alpha(#000000, 0.22);
                          border-radius: 12px; color: #fff; caret-color: #fff; }}
entry.glass-entry:focus-within {{ border-color: alpha({acc}, 0.8); box-shadow: 0 0 0 3px alpha({acc}, 0.25); }}
dropdown > button {{ border-radius: 10px; background-image: linear-gradient(180deg, alpha(#ffffff, 0.14), alpha(#ffffff, 0.07));
                    {pill} }}
scale trough {{ background: alpha(#000000, 0.18); border-radius: 99px; min-height: 6px;
               box-shadow: inset 0 1px 1px alpha(#000000, 0.25), 0 1px alpha(#ffffff, 0.08); }}
scale highlight {{ background-image: linear-gradient(180deg, alpha(#ffffff, 0.95), alpha(#ffffff, 0.75)); border-radius: 99px; }}
scale slider {{ background-image: linear-gradient(180deg, #ffffff, #e6e8f0); border-radius: 99px; min-width: 18px; min-height: 18px;
               margin: -6px; box-shadow: 0 1px 4px alpha(#000, 0.4), inset 0 -1px alpha(#000000, 0.08); }}
switch {{ background: alpha(#000000, 0.18); border-radius: 99px; border: 1px solid alpha(#ffffff, 0.10);
         box-shadow: inset 0 1px 2px alpha(#000000, 0.28); }}
switch:checked {{ background-image: linear-gradient(180deg, alpha({acc}, 0.95), alpha({acc}, 0.78)); border-color: alpha(#ffffff, 0.22); }}
switch slider {{ background-image: linear-gradient(180deg, #ffffff, #e6e8f0); border-radius: 99px; box-shadow: 0 1px 3px alpha(#000000, 0.35); }}
popover > contents {{ background: alpha({tint}, {max(0.9, t):.2f}); border-radius: 14px;
                     {glass_edges(top=0.28, bottom=0.10, side=0.12, sheen=0.10, edge=0.0)} }}
list.plain, list.plain row {{ background: transparent; }}
list.plain row {{ border-radius: 10px; }}
list.plain row:hover {{ background: alpha(#ffffff, 0.05); }}
scrolledwindow, viewport {{ background: transparent; }}
"""


# The red/yellow/green window buttons (traffic_lights below), in macOS's colours. They match the
# title bars Hyprland's hyprbars plugin draws on other apps' windows (hyprland.lua).
TRAFFIC_LIGHTS_CSS = """
.traffic-lights { margin-left: 4px; margin-right: 8px; }
.traffic-lights button { min-width: 13px; min-height: 13px; padding: 0; border-radius: 99px; border: none;
                         background-image: none; box-shadow: inset 0 0 0 0.5px alpha(#000, 0.25); color: alpha(#000, 0.6); }
.traffic-lights button label { font-size: 10px; font-weight: 800; opacity: 0; text-shadow: none; }
.traffic-lights:hover button label { opacity: 1; }
.traffic-lights button.tl-close { background-color: #ff5f57; }
.traffic-lights button.tl-min { background-color: #febc2e; }
.traffic-lights button.tl-full { background-color: #28c840; }
window.glass:backdrop .traffic-lights:not(:hover) button { background-color: alpha(#ffffff, 0.22); }
/* Windows that keep GTK's own buttons (dialogs such as a folder picker) get the same three dots */
windowcontrols { border-spacing: 8px; }
windowcontrols > button { min-width: 13px; min-height: 13px; padding: 0; margin: 0; border-radius: 99px;
                          border: none; background-image: none; box-shadow: inset 0 0 0 0.5px alpha(#000, 0.25); }
windowcontrols > button > image { background: none; box-shadow: none; padding: 0; margin: 0;
                                  -gtk-icon-size: 9px; color: transparent; }
windowcontrols:hover > button > image { color: alpha(#000, 0.6); }
windowcontrols > button.close { background-color: #ff5f57; }
windowcontrols > button.minimize { background-color: #febc2e; }
windowcontrols > button.maximize { background-color: #28c840; }
window:backdrop windowcontrols:not(:hover) > button { background-color: alpha(#ffffff, 0.22); }
/* Menus: only the rounded panel is drawn, with no square backing behind it */
popover.background, popover.menu { background: transparent; box-shadow: none; }
tooltip.background { background-color: alpha(#1c1d2a, 0.92); border: 1px solid alpha(#ffffff, 0.18);
                     border-radius: 12px; box-shadow: none; }
"""

# GTK's own window buttons, in the same order as the dots everywhere else
DECORATION_LAYOUT = "close,minimize,maximize:"


_css = {"prov": None, "extra": ""}


def _load_css(prov, extra):
    css = base_css() + TRAFFIC_LIGHTS_CSS + extra
    if hasattr(prov, "load_from_string"):
        prov.load_from_string(css)
    else:
        prov.load_from_data(css.encode())


def apply_css(extra=""):
    prov = Gtk.CssProvider()
    _load_css(prov, extra)
    try:
        Gtk.Settings.get_default().set_property("gtk-decoration-layout", DECORATION_LAYOUT)
    except Exception:
        pass
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css.update(prov=prov, extra=extra)
    return prov


def reload_css():
    """Restyle this app's windows after the Glass slider or accent colour changed."""
    if _css["prov"] is not None:
        _load_css(_css["prov"], _css["extra"])


def fit_size(win, width, height):
    """Default window size, shrunk to fit small screens (leaves room for the top bar and dock)."""
    try:
        mons = Gdk.Display.get_default().get_monitors()
        if mons.get_n_items():
            g = mons.get_item(0).get_geometry()
            width = min(width, int(g.width * 0.88))
            height = min(height, g.height - 160)
    except Exception:
        pass
    win.set_default_size(width, height)


# --------------------------------------------------------------------- tiny widget helpers
def label(text="", cls=None, xalign=0.0, wrap=False, markup=False, ellipsize=False, selectable=False):
    lb = Gtk.Label(xalign=xalign)
    lb.set_markup(text) if markup else lb.set_text(text)
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


def box(vertical=True, spacing=8, cls=None):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                spacing=spacing)
    for c in (cls or "").split():
        b.add_css_class(c)
    return b


def vbox(spacing=8, cls=None):
    return box(True, spacing, cls)


def hbox(spacing=8, cls=None):
    return box(False, spacing, cls)


def spacer():
    s = Gtk.Box()
    s.set_hexpand(True)
    return s


def button(text, cb, cls="pill"):
    b = Gtk.Button(label=text)
    for c in cls.split():
        b.add_css_class(c)
    b.connect("clicked", lambda *_: cb())
    return b


def icon_button(icon, cb, tooltip="", cls="round"):
    b = Gtk.Button.new_from_icon_name(icon)
    for c in cls.split():
        b.add_css_class(c)
    if tooltip:
        b.set_tooltip_text(tooltip)
    b.connect("clicked", lambda *_: cb())
    return b


def card(title=None, sub=None):
    c = vbox(10, "card")
    if title:
        c.append(label(title, "card-title"))
    if sub:
        c.append(label(sub, "dim small", wrap=True))
    return c


def clear(container):
    child = container.get_first_child()
    while child:
        nxt = child.get_next_sibling()
        container.remove(child)
        child = nxt


def setting_row(title, sub, widget):
    r = hbox(12, "row")
    t = vbox(2)
    t.set_hexpand(True)
    t.append(label(title))
    if sub:
        t.append(label(sub, "dim small", wrap=True))
    r.append(t)
    widget.set_valign(Gtk.Align.CENTER)
    r.append(widget)
    return r


# --------------------------------------------------------------------- moving windows by the title bar
def hypr(cmd):
    """Send one request to Hyprland's control socket and return its reply ("" if Hyprland isn't there)."""
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        return ""
    run = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(os.path.join(run, "hypr", sig, ".socket.sock"))
            s.sendall(cmd.encode())
            out = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                out += chunk
        return out.decode(errors="replace")
    except OSError:
        return ""


def work_areas():
    """Each screen's box (x0, y0, x1, y1) a window has to stay inside: the whole screen, minus the
    top bar and a small gap under it, plus where the screen itself starts (its top edge).
    Hyprland's config applies the same box when you let go of a window."""
    out = []
    try:
        mons = json.loads(hypr("j/monitors"))
    except ValueError:
        return out
    for m in mons:
        s = m.get("scale") or 1
        w, h = m["width"] / s, m["height"] / s
        if m.get("transform", 0) % 2:
            w, h = h, w
        top = (m.get("reserved") or [0, 0, 0, 0])[1]
        out.append((m["x"], m["y"] + (top + 6 if top else 0), m["x"] + w, m["y"] + h, m["y"]))
    return out


def my_window_address():
    """Hyprland's address for this app's focused window (or any of its windows)."""
    try:
        act = json.loads(hypr("j/activewindow") or "{}")
        if act.get("pid") == os.getpid():
            return act.get("address")
        for c in json.loads(hypr("j/clients") or "[]"):
            if c.get("pid") == os.getpid():
                return c.get("address")
    except ValueError:
        pass
    return None


def minimize(win):
    """Yellow button: hide the window on the "minimized" desktop, like every other window's
    yellow button (hyprland.lua). Clicking the app in the dock brings it back."""
    addr = my_window_address()
    if addr:
        hypr(f'dispatch hl.dsp.window.move({{ workspace = "special:minimized", follow = false, window = "address:{addr}" }})')
    else:
        win.minimize()


def traffic_lights(win):
    """The Mac-style red/yellow/green buttons, drawn the same as the title bars Hyprland puts on
    other apps: red closes, yellow minimizes, green toggles full size. Symbols show on hover."""
    lights = hbox(8, "traffic-lights no-drag")
    lights.set_valign(Gtk.Align.CENTER)
    for cls, sym, tip, cb in (
        ("tl-close", "×", "Close", win.close),
        ("tl-min", "−", "Minimize", lambda: minimize(win)),
        ("tl-full", "+", "Full size", lambda: win.unmaximize() if win.is_maximized() else win.maximize()),
    ):
        b = button(sym, cb, cls)
        b.set_tooltip_text(tip)
        b.set_valign(Gtk.Align.CENTER)
        lights.append(b)
    return lights


_INTERACTIVE = (Gtk.Button, Gtk.Editable, Gtk.DropDown, Gtk.MenuButton, Gtk.Switch, Gtk.Scale, Gtk.CheckButton)


def drag_by_titlebar(win, header):
    """Let people move the window by dragging its title bar.

    Apps normally ask the compositor to do this (xdg_toplevel.move), but Hyprland ignores that
    request, so a GlassOS window moves itself instead: while the button is held on an empty part
    of the title bar, it follows the pointer through Hyprland's control socket. Buttons, fields
    and tabs in the title bar keep working, and a double-click zooms the window or zooms it back.
    It reads the pointer position from Hyprland rather than from its own motion events, so it
    also works with the absolute pointers virtual machines use.
    It also swaps GTK's own window buttons for the red/yellow/green ones, first in the header."""
    header.set_show_title_buttons(False)
    lights = traffic_lights(win)
    header.pack_start(lights)
    lights.get_parent().reorder_child_after(lights, None)   # before anything the app packed
    g = Gtk.GestureDrag(button=1)
    g.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    st = {"timer": 0, "last_press": 0.0}

    def on_title(x, y):
        w = header.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None and w is not header:
            if isinstance(w, _INTERACTIVE) or w.has_css_class("no-drag"):
                return False
            w = w.get_parent()
        return True

    def begin(gesture, x, y):
        if not on_title(x, y):
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        now = time.monotonic()
        if now - st["last_press"] < 0.4:   # double-click: zoom between the top bar and dock, or back
            st["last_press"] = 0.0
            if win.is_maximized():
                win.unmaximize()
            elif my_window_address():
                hypr('eval glass_window("zoom")')   # acts on the active window: this one
            return
        st["last_press"] = now
        try:
            cur = json.loads(hypr("j/cursorpos"))
            act = json.loads(hypr("j/activewindow"))
        except ValueError:
            return
        if not act or act.get("pid") != os.getpid() or not act.get("floating", True):
            return
        st.update(addr=act["address"], dx=cur["x"] - act["at"][0], dy=cur["y"] - act["at"][1],
                  last=(act["at"][0], act["at"][1]), start=now, size=act["size"], areas=work_areas())
        if st["timer"]:
            GLib.source_remove(st["timer"])
        st["timer"] = GLib.timeout_add(16, tick)

    def tick():
        if time.monotonic() - st["start"] > 120:   # never follow the pointer forever
            st["timer"] = 0
            return False
        try:
            cur = json.loads(hypr("j/cursorpos"))
        except ValueError:
            return True
        x, y = cur["x"] - st["dx"], cur["y"] - st["dy"]
        for x0, y0, x1, y1, screen_top in st["areas"]:   # stop at the edges of the screen the pointer is on
            if x0 <= cur["x"] < x1 and screen_top <= cur["y"] < y1:
                x = max(x0, min(x, x1 - st["size"][0]))
                y = max(y0, min(y, y1 - st["size"][1]))
                break
        pos = (int(x), int(y))
        if pos != st["last"]:
            st["last"] = pos
            hypr(f'dispatch hl.dsp.window.move({{ x = {pos[0]}, y = {pos[1]}, window = "address:{st["addr"]}" }})')
        return True

    def end(*_a):
        if st["timer"]:
            GLib.source_remove(st["timer"])
            st["timer"] = 0

    g.connect("drag-begin", begin)
    g.connect("drag-end", end)
    g.connect("cancel", end)
    header.add_controller(g)
    return g
