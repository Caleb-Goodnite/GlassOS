"""Shared look for GlassOS's own apps ("Prism" glass).

Every GlassOS window is see-through: its background is a translucent tint and Hyprland blurs
whatever is behind it - including other windows. So one window over the wallpaper looks lightly
frosted, and each extra window stacked on top adds another layer of frost and tint, the way
real panes of glass do.

The tint strength is a setting (Settings > Appearance > Glass tint), stored in
~/.config/glassos/appearance.json, so every app picks it up when it starts.
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
DEFAULTS = {"tint": 0.42, "frost": 4, "accent": "#6aa8ff"}


def appearance():
    a = dict(DEFAULTS)
    try:
        with open(APPEARANCE) as f:
            a.update(json.load(f))
    except (OSError, ValueError):
        pass
    a["tint"] = max(0.1, min(0.9, float(a["tint"])))
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


def base_css():
    a = appearance()
    t = a["tint"]
    acc = a["accent"]
    return f"""
window.glass {{ background-color: alpha(#10111a, {t:.2f}); color: #f4f5fa; }}
window.glass.solid {{ background-color: alpha(#10111a, {min(0.95, t + 0.35):.2f}); }}
window.glass headerbar {{ background: transparent; box-shadow: none; border: none; min-height: 42px; color: #fff; }}
window.glass headerbar windowcontrols button {{ min-width: 14px; min-height: 14px; padding: 0; margin: 0 3px; }}
.glass-panel {{
  background: alpha(#ffffff, 0.06);
  border: 1px solid alpha(#ffffff, 0.10);
  border-top-color: alpha(#ffffff, 0.22);
  border-radius: 18px;
  box-shadow: inset 0 1px alpha(#ffffff, 0.06);
}}
.glass-pane {{ background: alpha(#ffffff, 0.035); }}
.sidebar-pane {{ background: alpha(#ffffff, 0.04); border-right: 1px solid alpha(#ffffff, 0.07); }}
.sidebar-pane list {{ background: transparent; }}
.sidebar-pane row {{ padding: 8px 12px; margin: 2px 10px; border-radius: 11px; color: alpha(#ffffff, 0.86); }}
.sidebar-pane row:selected {{ background: alpha(#ffffff, 0.15); color: #fff; box-shadow: inset 0 1px alpha(#ffffff, 0.12); }}
.sidebar-pane row:hover:not(:selected) {{ background: alpha(#ffffff, 0.06); }}
.page {{ padding: 24px 30px 36px 30px; }}
.page-title {{ font-size: 26px; font-weight: 800; }}
.page-sub {{ color: alpha(#ffffff, 0.86); }}
.card {{ background: alpha(#ffffff, 0.06); border: 1px solid alpha(#ffffff, 0.09);
        border-top-color: alpha(#ffffff, 0.2); border-radius: 16px; padding: 14px 16px; }}
.card-title {{ font-weight: 700; }}
.dim {{ color: alpha(#ffffff, 0.85); }}
.small {{ font-size: 12px; }}
.mono {{ font-family: "JetBrains Mono", monospace; font-size: 12px; }}
.row {{ padding: 8px 2px; border-bottom: 1px solid alpha(#ffffff, 0.06); }}
.ok {{ color: #5fe3a1; }}
.warn {{ color: #ffd479; }}
button.pill {{ border-radius: 99px; padding: 6px 16px; background: alpha(#ffffff, 0.12);
              border: 1px solid alpha(#ffffff, 0.16); box-shadow: none; color: #fff; }}
button.pill:hover {{ background: alpha(#ffffff, 0.2); }}
button.accent {{ background: alpha({acc}, 0.6); border-color: alpha(#ffffff, 0.3); }}
button.accent:hover {{ background: alpha({acc}, 0.8); }}
button.round {{ border-radius: 99px; min-width: 32px; min-height: 32px; padding: 0;
               background: alpha(#ffffff, 0.08); border: 1px solid alpha(#ffffff, 0.1); box-shadow: none; color: #fff; }}
button.round:hover {{ background: alpha(#ffffff, 0.18); }}
button.round:disabled {{ opacity: 0.35; }}
entry.glass-entry, entry {{ background: alpha(#ffffff, 0.08); border: 1px solid alpha(#ffffff, 0.14);
                          border-radius: 12px; color: #fff; caret-color: #fff; }}
entry.glass-entry:focus-within {{ border-color: alpha({acc}, 0.8); box-shadow: 0 0 0 3px alpha({acc}, 0.25); }}
dropdown > button {{ border-radius: 10px; background: alpha(#ffffff, 0.1); border: 1px solid alpha(#ffffff, 0.14); box-shadow: none; }}
scale trough {{ background: alpha(#ffffff, 0.14); border-radius: 99px; min-height: 6px; }}
scale highlight {{ background: alpha(#ffffff, 0.85); border-radius: 99px; }}
scale slider {{ background: #fff; border-radius: 99px; min-width: 18px; min-height: 18px; margin: -6px; box-shadow: 0 1px 4px alpha(#000, 0.4); }}
switch {{ background: alpha(#ffffff, 0.16); border-radius: 99px; }}
switch:checked {{ background: alpha({acc}, 0.85); }}
switch slider {{ background: #fff; border-radius: 99px; }}
popover > contents {{ background: alpha(#1a1b27, 0.92); border-radius: 14px; border: 1px solid alpha(#ffffff, 0.12); }}
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
"""


def apply_css(extra=""):
    prov = Gtk.CssProvider()
    css = base_css() + TRAFFIC_LIGHTS_CSS + extra
    if hasattr(prov, "load_from_string"):
        prov.load_from_string(css)
    else:
        prov.load_from_data(css.encode())
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    return prov


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
