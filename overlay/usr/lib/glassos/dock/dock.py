#!/usr/bin/python3
"""GlassOS Dock - a frosted-glass dock for pinned and running apps.

Left-click: open the app (or bring its window forward if it's already running).
Right-click: new window / close / keep in dock.
Pinned apps are listed in ~/.config/glassos/dock.conf.

The dock's size comes from Settings > Appearance > Dock size; it always sits centred on the
screen. The icon under the pointer lifts a little (Settings can turn that off). While a window is full
size (or when "Hide the dock automatically" is on), the dock gets out of the way and comes back
up when the pointer touches the bottom edge of the screen.

The top edge works like a Mac's full screen too: while a window is full size, touching the top of
the screen calls up the top bar and, under it, the window's title bar with red, yellow and green
buttons (red closes, yellow minimizes, green takes the window back to the size it had). They live
here because the dock already follows the pointer and the full-size window.
"""
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402
from gi.repository import Gtk4LayerShell as Layer  # noqa: E402

CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "glassos", "dock.conf")
APPEARANCE = os.path.join(os.path.dirname(CONF), "appearance.json")   # Settings > Appearance > Dock size
SIZES = {"small": 30, "medium": 36, "large": 46}                       # icon size in pixels
ICON_SIZE = SIZES["medium"]
THEMES = {"color": "Glass", "clear": "Glass-Clear", "dark": "Glass-Dark"}   # Settings > Icon style


def appearance():
    try:
        with open(APPEARANCE) as f:
            a = json.load(f)
        return a if isinstance(a, dict) else {}
    except (OSError, ValueError):
        return {}


def dock_icon_size(a=None):
    """Settings > Appearance > Dock size: a pixel size from the slider, or an older preset name."""
    a = appearance() if a is None else a
    v = a.get("dock_icon")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(max(24, min(80, v)))
    return SIZES.get(a.get("dock_size"), SIZES["medium"])


def dock_hover_animation(a=None):
    """Settings > Appearance > Animate icons on hover (on by default)."""
    a = appearance() if a is None else a
    return bool(a.get("dock_hover", True))


HOVER_SCALE = 1.12    # how much the icon under the pointer grows, when hover animation is on


def hover_lift(size):
    """px the icon under the pointer rises."""
    return round(size * 0.14)


def dock_glass():
    """Settings > Appearance > Glass, 0 (Clear) to 1 (Frosted): the dock's glass follows it."""
    try:
        with open(APPEARANCE) as f:
            a = json.load(f)
        if "glass" in a:
            return max(0.0, min(1.0, float(a["glass"]) / 100))
        return max(0.0, min(1.0, (float(a["tint"]) - 0.28) / 0.44))   # saved before the slider
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 0.35


CSS = b"""
window.glass-dock { background: transparent; }
.dock {
  /* a sheet of glass, as in macOS Golden Gate: light on the top edge and, fainter, on the bottom
     edge where it passes back out, with a darker band just inside the rim. How milky the fill is
     follows the Glass slider (apply_size). */
  border: 1px solid alpha(#ffffff, 0.16);
  border-top-color: alpha(#ffffff, 0.46);
  border-bottom-color: alpha(#ffffff, 0.24);
  border-radius: 26px;
  padding: 6px 8px 3px 8px;
  margin: 22px 16px 10px 16px;
  /* no outer shadow: it would be clipped into a box at the surface edge */
  box-shadow: inset 0 1px 1px alpha(#ffffff, 0.20), inset 0 -1px 1px alpha(#ffffff, 0.07),
              inset 0 0 0 1px alpha(#000000, 0.12);
}
.dock-item {
  background: none;
  border: none;
  box-shadow: none;
  padding: 3px 4px 0 4px;
  margin: 0 1px;
  border-radius: 16px;
}
/* The icon under the pointer lifts (sizes set in Dock.apply_size). Only the image moves, with a
   transform, so the bar's layout and width never change and nothing beside it shifts. */
.dock-item image { transform-origin: 50% 100%; }
.dock.animate .dock-item image { transition: transform 150ms cubic-bezier(0.2, 0.9, 0.3, 1); }
.dock-item:active image { opacity: 0.8; }
.dock { transition: transform 240ms cubic-bezier(0.2, 0.9, 0.3, 1); }
/* tucked below the screen edge while the dock is hidden */
.dock.tucked { transform: translateY(140px); }
.dot {
  min-width: 5px; min-height: 5px; border-radius: 3px;
  margin-top: 3px; margin-bottom: 2px;
  background: transparent;
}
.dot.running { background: alpha(#ffffff, 0.9); box-shadow: 0 0 4px alpha(#ffffff, 0.6); }
.dot.focused { background: #ffffff; min-width: 12px; }
.dot.running.minimized { background: alpha(#ffffff, 0.4); box-shadow: none; }
.dock-sep { min-width: 1px; background: alpha(#ffffff, 0.25); margin: 10px 7px 12px 7px; }
popover.dock-menu > contents {
  background: alpha(#1d1e2b, 0.92);
  border: 1px solid alpha(#ffffff, 0.2);
  border-radius: 14px;
  padding: 6px;
}
popover.dock-menu button { background: none; border: none; box-shadow: none; padding: 6px 14px; border-radius: 8px; color: #fff; }
popover.dock-menu button:hover { background: alpha(#ffffff, 0.14); }
popover.dock-menu label.title { font-weight: 700; padding: 4px 14px 6px 14px; color: alpha(#ffffff, 0.85); }
tooltip { background: alpha(#1c1d2a, 0.92); border-radius: 10px; border: 1px solid alpha(#ffffff, 0.18); }
popover.dock-label > contents {
  background: alpha(#1c1d2a, 0.88); border: 1px solid alpha(#ffffff, 0.18); border-radius: 9px;
  padding: 3px 10px; color: #ffffff; font-weight: 500; box-shadow: none;
}
/* The full-size window's title bar, called up from the top edge (TitleStrip). Dark glass like the
   title bars hyprbars draws (hyprland.lua), a little denser so its title stays readable over a white
   page, with the top bar's rim so the two read as one family. */
window.glass-titlebar { background: transparent; }
.fs-title {
  min-height: 34px;
  padding: 0 14px;
  border-radius: 17px;
  background-color: alpha(#10111a, 0.62);
  border: 1px solid alpha(#ffffff, 0.14);
  border-top-color: alpha(#ffffff, 0.42);
  border-bottom-color: alpha(#ffffff, 0.20);
  box-shadow: inset 0 1px 1px alpha(#ffffff, 0.16), inset 0 -1px 1px alpha(#ffffff, 0.05);
  color: alpha(#ffffff, 0.88);
  font-size: 13px;
  font-weight: 500;
}
/* the same buttons as glassui.TRAFFIC_LIGHTS_CSS, symbols on hover */
.traffic-lights button { min-width: 13px; min-height: 13px; padding: 0; border-radius: 99px; border: none;
                         background-image: none; box-shadow: inset 0 0 0 0.5px alpha(#000, 0.25); color: alpha(#000, 0.6); }
.traffic-lights button label { font-size: 10px; font-weight: 800; opacity: 0; text-shadow: none; }
.traffic-lights:hover button label { opacity: 1; }
.traffic-lights button.tl-close { background-color: #ff5f57; }
.traffic-lights button.tl-min { background-color: #febc2e; }
.traffic-lights button.tl-full { background-color: #28c840; }
"""


# ----------------------------------------------------------------------------- Hyprland
def hypr_dir():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    run = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(run, "hypr", sig) if sig else None


def hypr_request(cmd):
    d = hypr_dir()
    if not d:
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(os.path.join(d, ".socket.sock"))
        s.sendall(cmd.encode())
        chunks = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            chunks.append(b)
        s.close()
        return b"".join(chunks).decode(errors="replace")
    except OSError:
        return None


def clients():
    out = hypr_request("j/clients")
    if out is None:
        try:
            out = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True, timeout=2).stdout
        except Exception:
            return []
    try:
        return [c for c in json.loads(out) if c.get("mapped", True)]
    except Exception:
        return []


def active_address():
    out = hypr_request("j/activewindow")
    try:
        return json.loads(out).get("address") if out else None
    except Exception:
        return None


def focus_window(address):
    subprocess.Popen(["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{address}" }})'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


MINIMIZED = "special:minimized"   # where the yellow title-bar button puts windows (hyprland.lua)


def is_minimized(win):
    return (win.get("workspace") or {}).get("name") == MINIMIZED


def restore_window(address):
    """Bring a minimized window back onto the desktop you're looking at, and focus it."""
    try:
        ws = json.loads(hypr_request("j/activeworkspace") or "{}").get("id")
    except ValueError:
        ws = None
    if ws is not None:
        subprocess.run(["hyprctl", "dispatch",
                        f'hl.dsp.window.move({{ workspace = {int(ws)}, follow = false, window = "address:{address}" }})'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    focus_window(address)


def close_window(address):
    subprocess.Popen(["hyprctl", "dispatch", f'hl.dsp.window.close({{ window = "address:{address}" }})'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def listen_events(callback):
    """Call callback() on window open/close/focus events (Hyprland socket2)."""
    def once():
        callback()
        return False   # an idle callback that returns True runs again and again, using a whole core

    def run():
        while True:
            d = hypr_dir()
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(os.path.join(d, ".socket2.sock"))
                f = s.makefile("r", errors="replace")
                for line in f:
                    ev = line.split(">>", 1)[0]
                    if ev in ("openwindow", "closewindow", "activewindowv2", "movewindowv2", "windowtitlev2",
                              "fullscreen", "workspacev2"):
                        GLib.idle_add(once)
            except Exception:
                pass
            GLib.idle_add(once)
            threading.Event().wait(2.0)

    threading.Thread(target=run, daemon=True).start()


# ----------------------------------------------------------------------------- apps
_all_apps = None
_scanned = 0.0


def squash(text):
    """'org.tuxpaint.Tuxpaint' and 'Tux Paint' both become 'tuxpaint', for loose matching."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def app_for_class(cls):
    """Find the .desktop entry for a window class / Wayland app_id."""
    global _all_apps, _scanned
    if not cls:
        return None
    for cand in (cls, cls.lower()):
        try:
            info = Gio.DesktopAppInfo.new(cand + ".desktop")
            if info:
                return info
        except TypeError:
            pass
    # rescan now and then, so apps installed since the dock started are found too
    if _all_apps is None or time.monotonic() - _scanned > 5:
        _all_apps = [a for a in Gio.AppInfo.get_all() if isinstance(a, Gio.DesktopAppInfo)]
        _scanned = time.monotonic()
    lc = cls.lower()
    for a in _all_apps:
        wm = (a.get_startup_wm_class() or "").lower()
        if wm == lc:
            return a
    for a in _all_apps:
        exe = os.path.basename((a.get_executable() or "")).lower()
        if exe == lc or a.get_id().lower().startswith(lc):
            return a
    # loose match, for apps whose window class doesn't follow their launcher's id
    # (an App Store app "org.tuxpaint.Tuxpaint" whose window says "TuxPaint.TuxPaint")
    want = {squash(cls), squash(cls.rsplit(".", 1)[-1])} - {""}
    for a in _all_apps:
        app_id = a.get_id()[:-len(".desktop")] if a.get_id().endswith(".desktop") else a.get_id()
        if want & {squash(app_id.rsplit(".", 1)[-1]), squash(a.get_name())}:
            return a
    return None


def launch(info):
    cmd = info.get_commandline() or info.get_executable()
    if not cmd:
        return
    argv = [a for a in shlex.split(cmd) if not (len(a) == 2 and a.startswith("%"))]
    if info.get_boolean("Terminal"):
        argv = ["foot", "-e"] + argv
    subprocess.Popen(["glass-launch"] + argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def read_pins():
    try:
        with open(CONF) as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except OSError:
        return ["thunar.desktop", "firefox-esr.desktop", "foot.desktop", "os.glass.Lens.desktop"]


def write_pins(pins):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, "w") as f:
        f.write("# Apps pinned to the dock, in order (desktop file IDs).\n")
        for p in pins:
            f.write(p + "\n")


# ----------------------------------------------------------------------------- UI
class DockItem(Gtk.Button):
    def __init__(self, dock, app_id, info, gicon=None, name=None, action=None):
        super().__init__()
        self.dock = dock
        self.action = action
        self.app_id = app_id
        self.info = info
        self.windows = []
        self.add_css_class("dock-item")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        icon = Gtk.Image()
        gi_ = gicon or (info.get_icon() if info else None)
        if gi_:
            icon.set_from_gicon(gi_)
        else:
            icon.set_from_icon_name("application-x-executable")
        icon.set_pixel_size(ICON_SIZE)
        self.icon = icon
        self.dot = Gtk.Box()
        self.dot.add_css_class("dot")
        self.dot.set_halign(Gtk.Align.CENTER)
        box.append(icon)
        box.append(self.dot)
        self.set_child(box)
        self.name = name or (info.get_display_name() if info else app_id)
        self.label_pop = None
        self.label_id = None
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_: self.show_label())
        hover.connect("leave", lambda *_: self.hide_label())
        self.add_controller(hover)
        self.connect("clicked", self.on_click)
        rc = Gtk.GestureClick(button=3)
        rc.connect("pressed", self.on_right_click)
        self.add_controller(rc)

    def show_label(self):
        """The app's name, floating above the icon like on a Mac. (A tooltip would sit on top
        of the lifted icon: GTK places it against the button.)"""
        if self.label_id:
            GLib.source_remove(self.label_id)

        def pop():
            self.label_id = None
            if self.dock.menus:
                return False
            if not self.label_pop:
                self.label_pop = Gtk.Popover()
                self.label_pop.add_css_class("dock-label")
                self.label_pop.set_has_arrow(False)
                self.label_pop.set_autohide(False)
                self.label_pop.set_can_target(False)
                self.label_pop.set_position(Gtk.PositionType.TOP)
                self.label_pop.set_child(Gtk.Label(label=self.name))
                self.label_pop.set_parent(self)
            grow = hover_lift(ICON_SIZE) + round(ICON_SIZE * (HOVER_SCALE - 1))
            rise = (grow if self.dock.hover_anim else 0) + 6
            r = Gdk.Rectangle()
            r.x, r.y, r.width, r.height = 0, -rise, max(1, self.get_width()), 1
            self.label_pop.set_pointing_to(r)
            self.label_pop.popup()
            return False
        self.label_id = GLib.timeout_add(80, pop)

    def hide_label(self):
        if self.label_id:
            GLib.source_remove(self.label_id)
            self.label_id = None
        if self.label_pop:
            self.label_pop.popdown()

    def get_tooltip_text(self):   # the app's name (the right-click menu's title uses it)
        return self.name

    def set_windows(self, wins, active):
        self.windows = wins
        self.dot.remove_css_class("running")
        self.dot.remove_css_class("focused")
        self.dot.remove_css_class("minimized")
        if wins:
            self.dot.add_css_class("running")
            if all(is_minimized(w) for w in wins):
                self.dot.add_css_class("minimized")
            if any(w.get("address") == active for w in wins):
                self.dot.add_css_class("focused")

    def on_click(self, _btn):
        if self.action:
            self.action()
            return
        if self.windows:
            # cycle through this app's windows, most recently used first
            wins = sorted(self.windows, key=lambda w: w.get("focusHistoryID", 99))
            active = active_address()
            target = wins[0]
            if target.get("address") == active and len(wins) > 1:
                target = wins[1]
            if is_minimized(target):
                restore_window(target["address"])
            else:
                focus_window(target["address"])
        elif self.info:
            launch(self.info)

    def on_right_click(self, *_):
        pop = Gtk.Popover()
        pop.add_css_class("dock-menu")
        pop.set_has_arrow(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title = Gtk.Label(label=self.get_tooltip_text() or "", xalign=0)
        title.add_css_class("title")
        box.append(title)

        def item(label, fn):
            b = Gtk.Button(label=label)
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda *_: (pop.popdown(), fn()))
            box.append(b)

        if self.info:
            item("New Window", lambda: launch(self.info))
        if self.windows:
            item("Close" if len(self.windows) == 1 else f"Close {len(self.windows)} Windows",
                 lambda: [close_window(w["address"]) for w in self.windows])
        if self.info and not self.action:
            pinned = self.app_id in self.dock.pins
            item("Remove from Dock" if pinned else "Keep in Dock", lambda: self.dock.toggle_pin(self.app_id))
        pop.set_child(box)
        pop.set_parent(self)
        self.dock.menus += 1           # the dock stays up while one of its menus is open
        pop.connect("closed", lambda *_: self.dock.menu_closed())
        pop.popup()


# ----------------------------------------------------------------------------- full size: the top edge
WAYBAR_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "waybar")
TITLE_TOP = 46      # the title strip sits under the top bar: its 6 px margin, 34 px height, then a 6 px gap
TITLE_HEIGHT = 34   # as tall as the title bars hyprbars draws


class TopBarCopy:
    """A second copy of the top bar on Hyprland's overlay layer, hidden until it's called up over a
    full-size window. Hyprland draws the normal bar (top layer) under full-screen windows and has no
    rule to lift it, so the copy runs from the same top.jsonc and top.css with three changes.

    Debian's Waybar (0.12) can only toggle its bars on SIGUSR1, so this keeps track of which way
    round they are. It also takes no space of its own (exclusive false), which makes Hyprland place it
    below the space the normal bar keeps; a negative top margin of that size puts it back on top."""

    def __init__(self):
        self.proc = None
        self.shown = False
        self.ready_at = 0.0
        self.offset = None
        self.conf = os.path.join(GLib.get_user_runtime_dir(), "glassos", "top-fullsize.jsonc")

    def bar_margin(self):
        try:
            with open(os.path.join(WAYBAR_DIR, "top.jsonc")) as f:
                m = re.search(r'"margin-top"\s*:\s*(-?\d+)', f.read())
            return int(m.group(1)) if m else 0
        except OSError:
            return 0

    def start(self, reserved_top):
        top = os.path.join(WAYBAR_DIR, "top.jsonc")
        if not shutil.which("waybar") or not os.path.exists(top):
            return
        self.offset = reserved_top
        os.makedirs(os.path.dirname(self.conf), exist_ok=True)
        with open(self.conf, "w") as f:
            json.dump({"include": [top], "layer": "overlay", "exclusive": False, "start_hidden": True,
                       "margin-top": self.bar_margin() - reserved_top}, f)
        self.shown = False
        self.ready_at = time.monotonic() + 1.5   # SIGUSR1 ends a Waybar that hasn't set up its handler yet
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGUSR2)   # reread the config
            return
        cmd = ["waybar", "-c", self.conf, "-s", os.path.join(WAYBAR_DIR, "top.css")]
        if shutil.which("systemd-run"):
            # its own scope, like the rest of the desktop (session-start), so Glass Lens can show it.
            # A copy left by an earlier dock is stopped first.
            subprocess.run(["systemctl", "--user", "stop", "glass-topbar-fullsize.scope"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--slice=glass-desktop.slice",
                   "--unit=glass-topbar-fullsize", "--description=GlassOS desktop: top bar over full-size windows",
                   "--"] + cmd
        # without the dock's gtk4-layer-shell preload (glass-dock), which would turn Waybar's GTK 3
        # bar into an ordinary window
        env = {k: v for k, v in os.environ.items() if k != "LD_PRELOAD"}
        try:
            self.proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.proc = None

    def show(self, reserved_top):
        if reserved_top != self.offset or not self.proc or self.proc.poll() is not None:
            self.start(reserved_top)
        self.toggle_to(True)

    def hide(self):
        self.toggle_to(False)

    def toggle_to(self, shown):
        if shown == self.shown or not self.proc or self.proc.poll() is not None:
            return
        if time.monotonic() < self.ready_at:
            return
        self.proc.send_signal(signal.SIGUSR1)
        self.shown = shown


class TitleStrip(Gtk.Window):
    """The full-size window's own title bar, under the top bar while that's called up."""

    def __init__(self, app, dock):
        super().__init__(application=app)
        self.dock = dock
        self.address = None
        self.add_css_class("glass-titlebar")
        self.set_decorated(False)
        Layer.init_for_window(self)
        Layer.set_namespace(self, "glass-titlebar")
        Layer.set_layer(self, Layer.Layer.OVERLAY)
        for edge, margin in ((Layer.Edge.TOP, TITLE_TOP), (Layer.Edge.LEFT, 10), (Layer.Edge.RIGHT, 10)):
            Layer.set_anchor(self, edge, True)
            Layer.set_margin(self, edge, margin)
        Layer.set_exclusive_zone(self, -1)
        Layer.set_keyboard_mode(self, Layer.KeyboardMode.NONE)
        bar = Gtk.CenterBox()
        bar.add_css_class("fs-title")
        lights = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lights.add_css_class("traffic-lights")
        lights.set_valign(Gtk.Align.CENTER)
        for cls, sym, tip, action in (("tl-close", "×", "Close", "close"),
                                      ("tl-min", "−", "Minimize", "minimize"),
                                      ("tl-full", "+", "Leave full size", "full")):
            b = Gtk.Button(label=sym)
            b.add_css_class(cls)
            b.set_tooltip_text(tip)
            b.set_valign(Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, a=action: self.act(a))
            lights.append(b)
        bar.set_start_widget(lights)
        self.title = Gtk.Label()
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.title.set_max_width_chars(80)
        bar.set_center_widget(self.title)
        self.set_child(bar)

    def act(self, action):
        if self.address and re.fullmatch(r"0x[0-9a-fA-F]+", self.address):
            subprocess.Popen(["hyprctl", "eval", f'glass_window("{action}", "{self.address}")'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.dock.hide_top()

    def show_for(self, win, monitor_name):
        self.address = win.get("address")
        self.title.set_text(win.get("title") or win.get("class") or "")
        ms = Gdk.Display.get_default().get_monitors()
        for i in range(ms.get_n_items()):
            if ms.get_item(i).get_connector() == monitor_name:
                Layer.set_monitor(self, ms.get_item(i))
        self.set_visible(True)


class Dock(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.add_css_class("glass-dock")
        self.set_decorated(False)
        # A resizable GTK window keeps the biggest size it has ever had, so the glass would stay wide
        # after the bar gets narrower (an app closes, the dock shrinks). Non-resizable windows always
        # take their content's natural size.
        self.set_resizable(False)
        self.fit_id = None
        Layer.init_for_window(self)
        Layer.set_namespace(self, "glass-dock")
        Layer.set_layer(self, Layer.Layer.TOP)
        Layer.set_anchor(self, Layer.Edge.BOTTOM, True)
        Layer.set_keyboard_mode(self, Layer.KeyboardMode.NONE)
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.box.add_css_class("dock")
        self.set_child(self.box)
        self.pins = read_pins()
        self.items = {}
        self.signature = None
        self.size_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.size_css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.hover_anim = None
        self.size_key = None         # the CSS last loaded, so an unrelated settings change costs nothing
        # whether the pointer is anywhere on the dock (for hiding)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self.on_enter)
        motion.connect("leave", self.on_leave)
        self.add_controller(motion)
        # hiding: while a window is full size, or always with "Hide the dock automatically"
        self.autohide = bool(appearance().get("dock_autohide", False))
        self.fullscreen = False
        self.hidden_mode = False     # out of the way until the pointer touches the bottom edge
        self.revealed = True
        self.hovering = False
        self.menus = 0
        self.hide_id = None
        self.monitors = []
        self.monitors_at = 0.0
        self.icon_theme = None
        # the top edge, while a window is full size
        self.fs_window = None
        self.top_bar = TopBarCopy()
        self.title_strip = TitleStrip(app, self)
        self.top_revealed = False
        self.top_hide_id = None
        self.apply_size()
        # Settings saves appearance.json; pick up a new dock size straight away
        self.appearance_mon = Gio.File.new_for_path(APPEARANCE).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.appearance_mon.connect("changed", lambda *_a: self.apply_size(rebuild=False))
        self.refresh()
        listen_events(self.refresh)
        GLib.timeout_add_seconds(3, self.refresh)  # safety net
        GLib.timeout_add(90, self.watch_edge)
        if self.autohide:
            GLib.idle_add(lambda: (self.update_hidden_mode(), False)[1])
        Gio.AppInfoMonitor.get().connect("changed", lambda *_: self.rebuild())

    def apply_size(self, rebuild=True):
        global ICON_SIZE
        a = appearance()
        old_size = ICON_SIZE
        ICON_SIZE = dock_icon_size(a)
        hover = dock_hover_animation(a)
        if hover != self.hover_anim:
            self.hover_anim = hover
            (self.box.add_css_class if hover else self.box.remove_css_class)("animate")
        theme = THEMES.get(a.get("icon_style"), THEMES["dark"])
        if theme != self.icon_theme:
            self.icon_theme = theme
            Gtk.Settings.get_default().set_property("gtk-icon-theme-name", theme)
            rebuild = True
        rebuild = rebuild or ICON_SIZE != old_size
        autohide = bool(a.get("dock_autohide", False))
        if autohide != self.autohide:
            self.autohide = autohide
            GLib.idle_add(lambda: (self.update_hidden_mode(), False)[1])
        g = dock_glass()
        top, bottom = 0.15 + 0.07 * g, 0.08 + 0.08 * g   # clear glass barely tints; frosted is milkier
        # room above the bar for a lifted icon: fixed for a given size, so the surface never resizes
        # while the pointer moves (that resizing is what used to shove the dock off centre)
        lift = hover_lift(ICON_SIZE)
        headroom = max(22, lift + round(ICON_SIZE * (HOVER_SCALE - 1)) + 8)
        css = (f".dock {{ border-radius: {round((ICON_SIZE + 22) * 0.38)}px; margin-top: {headroom}px; "
               f"background-image: linear-gradient(180deg, alpha(#ffffff, {top:.3f}), alpha(#ffffff, {bottom:.3f})); }}"
               f".dock.tucked {{ transform: translateY({ICON_SIZE + 60}px); }}"
               f".dock.animate .dock-item:hover image {{ transform: translateY(-{lift}px) scale({HOVER_SCALE}); }}")
        if css != self.size_key:
            self.size_key = css
            if hasattr(self.size_css, "load_from_string"):
                self.size_css.load_from_string(css)
            else:
                self.size_css.load_from_data(css.encode())
        # the bar is the icon plus 22 px of padding and dots, with 10 px under it; windows that
        # are maximized or tiled stop above it
        self.set_exclusive()
        if rebuild and self.items:
            self.rebuild()
        elif self.items:
            self.fit()

    def fit(self):
        """Shrink the surface back to the bar's own width (see set_resizable in __init__)."""
        if self.fit_id:
            return

        def go():
            self.fit_id = None
            self.set_default_size(1, 1)
            self.queue_resize()
            return False
        self.fit_id = GLib.idle_add(go)

    def set_exclusive(self):
        # while the dock hides itself, windows may use the whole screen
        Layer.set_exclusive_zone(self, 0 if self.autohide else ICON_SIZE + 28)

    def toggle_pin(self, app_id):
        if app_id in self.pins:
            self.pins.remove(app_id)
        else:
            self.pins.append(app_id)
        write_pins(self.pins)
        self.rebuild()

    def rebuild(self):
        global _all_apps
        _all_apps = None
        self.signature = None
        self.refresh()

    def refresh(self):
        cl = clients()
        active = active_address()
        aw = next((c for c in cl if c.get("address") == active), None)
        fs = bool(aw) and aw.get("fullscreen") == 2 and not is_minimized(aw)
        self.fs_window = aw if fs else None
        if fs != self.fullscreen:
            self.fullscreen = fs
            self.update_hidden_mode()
            if fs and self.top_bar.proc is None:
                # the first time anything goes full size, so it's ready by the time the pointer gets there
                self.top_bar.start(self.reserved_top(aw.get("monitor")))
        if self.top_revealed:
            if not fs or aw.get("address") != self.title_strip.address:
                self.hide_top()
            else:
                self.title_strip.title.set_text(aw.get("title") or aw.get("class") or "")
        running = {}   # app_id -> (info, [windows])
        for c in cl:
            cls = c.get("class") or c.get("initialClass") or ""
            if not cls or cls in ("glass-dock",):
                continue
            info = app_for_class(cls)
            key = info.get_id() if info else "class:" + cls
            running.setdefault(key, [info, []])[1].append(c)

        order = list(self.pins)
        extra = [k for k in running if k not in self.pins]
        signature = (tuple(order), tuple(extra))
        if signature != self.signature:
            self.signature = signature
            child = self.box.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                self.box.remove(child)
                child = nxt
            self.items = {}
            for app_id in order:
                try:
                    info = Gio.DesktopAppInfo.new(app_id)
                except TypeError:
                    info = None
                if not info:
                    continue
                it = DockItem(self, app_id, info)
                self.items[app_id] = it
                self.box.append(it)
            if extra:
                sep = Gtk.Box()
                sep.add_css_class("dock-sep")
                self.box.append(sep)
                for k in extra:
                    info, wins = running[k]
                    name = info.get_display_name() if info else k.split(":", 1)[1]
                    gicon = None if info else Gio.ThemedIcon.new_from_names([k.split(":", 1)[1].lower(),
                                                                             "application-x-executable"])
                    it = DockItem(self, k, info, gicon=gicon, name=name)
                    self.items[k] = it
                    self.box.append(it)
            sep = Gtk.Box()
            sep.add_css_class("dock-sep")
            self.box.append(sep)
            apps = DockItem(self, "glass:apps", None,
                            gicon=Gio.ThemedIcon.new_from_names(["glass-apps", "view-app-grid", "applications-all",
                                                                 "view-grid", "applications-other"]),
                            name="All Apps (Super)",
                            action=lambda: subprocess.Popen(["sh", "-c", "glass-sound launcher; fuzzel"]))
            self.box.append(apps)
            self.items["glass:apps"] = apps
            self.fit()

        for k, it in self.items.items():
            it.set_windows(running.get(k, [None, []])[1], active)
        return True


    # ------------------------------------------------------------------------- pointer
    def on_enter(self, _c, _x, _y):
        self.hovering = True
        self.cancel_hide()

    def on_leave(self, _c):
        self.hovering = False
        self.fit()
        if self.hidden_mode:
            self.schedule_hide()

    # ------------------------------------------------------------------------- hiding
    def update_hidden_mode(self):
        hidden = self.autohide or self.fullscreen
        self.set_exclusive()
        if hidden == self.hidden_mode:
            return
        self.hidden_mode = hidden
        if hidden:
            if not self.hovering:
                self.hide_now()
        else:
            self.cancel_hide()
            self.show_now()

    def show_now(self):
        self.revealed = True
        # above a full-size window while it's called up; with the top bar otherwise
        Layer.set_layer(self, Layer.Layer.OVERLAY if self.fullscreen else Layer.Layer.TOP)
        if self.get_visible():
            self.box.remove_css_class("tucked")
            return
        self.box.add_css_class("tucked")
        self.set_visible(True)
        # map it tucked below the edge, then let it slide up
        GLib.timeout_add(30, lambda: (self.box.remove_css_class("tucked"), False)[1])

    def hide_now(self):
        self.hide_id = None
        if not self.hidden_mode or self.hovering or self.menus:
            return False
        self.revealed = False
        self.box.add_css_class("tucked")

        def unmap():
            # unmapped once it's slid away, so the space it leaves takes no clicks
            if not self.revealed:
                self.set_visible(False)
            return False
        GLib.timeout_add(260, unmap)
        return False

    def schedule_hide(self, delay=450):
        self.cancel_hide()
        self.hide_id = GLib.timeout_add(delay, self.hide_now)

    def cancel_hide(self):
        if self.hide_id:
            GLib.source_remove(self.hide_id)
            self.hide_id = None

    def menu_closed(self):
        self.menus = max(0, self.menus - 1)
        if self.hidden_mode and not self.hovering:
            self.schedule_hide()

    def watch_edge(self):
        """While hidden, call the dock up when the pointer reaches the bottom edge of the screen."""
        if not self.hidden_mode:
            return True
        try:
            pos = json.loads(hypr_request("j/cursorpos") or "{}")
            x, y = float(pos["x"]), float(pos["y"])
        except (ValueError, KeyError, TypeError):
            return True
        if not self.monitors or time.monotonic() - self.monitors_at > 5:
            try:
                self.monitors = json.loads(hypr_request("j/monitors") or "[]")
            except ValueError:
                self.monitors = []
            self.monitors_at = time.monotonic()
        for m in self.monitors:
            sc = m.get("scale") or 1
            w, h = m.get("width", 0) / sc, m.get("height", 0) / sc
            if (m.get("transform") or 0) % 2 == 1:
                w, h = h, w
            mx, my = m.get("x", 0), m.get("y", 0)
            if mx <= x < mx + w and my <= y < my + h:
                if self.fullscreen:
                    self.watch_top(m, y - my)
                if y >= my + h - 3:
                    self.cancel_hide()
                    if not self.revealed:
                        self.show_now()
                elif (self.revealed and not self.hovering and not self.menus and not self.hide_id
                      and y < my + h - (ICON_SIZE + 40)):
                    self.schedule_hide(250)
                break
        return True


    # ------------------------------------------------------------------------- the top edge
    def reserved_top(self, monitor_id):
        """The space the top bar keeps at the top of a screen."""
        try:
            mons = json.loads(hypr_request("j/monitors") or "[]")
        except ValueError:
            mons = []
        for m in mons:
            if m.get("id") == monitor_id:
                r = m.get("reserved") or []
                return int(r[1]) if len(r) > 1 else 0
        return 0

    def watch_top(self, m, dy):
        """While a window is full size, the top edge of its screen calls up the top bar and the
        window's title bar; they go again once the pointer moves down past them."""
        here = self.fs_window is not None and m.get("id") == self.fs_window.get("monitor")
        near = here and dy <= TITLE_TOP + TITLE_HEIGHT + 20
        if here and dy <= 1:
            self.cancel_top_hide()
            if not self.top_revealed:
                self.top_revealed = True
                r = m.get("reserved") or []
                self.top_bar.show(int(r[1]) if len(r) > 1 else 0)
                self.title_strip.show_for(self.fs_window, m.get("name"))
        elif not self.top_revealed:
            return
        elif near:
            self.cancel_top_hide()
            self.top_bar.toggle_to(True)   # in case the bar wasn't ready when the strip came up
        elif not self.top_hide_id and not self.top_menu_open():
            def go():
                self.top_hide_id = None
                self.hide_top()
                return False
            self.top_hide_id = GLib.timeout_add(300, go)

    def top_menu_open(self):
        """A drop-down or the GlassOS menu opened from the called-up top bar keeps it up."""
        try:
            layers = json.loads(hypr_request("j/layers") or "{}")
        except ValueError:
            return False
        for mon in layers.values():
            for level in (mon.get("levels") or {}).values():
                if any(ls.get("namespace") in ("glass-panel", "launcher") for ls in level):
                    return True
        return False

    def cancel_top_hide(self):
        if self.top_hide_id:
            GLib.source_remove(self.top_hide_id)
            self.top_hide_id = None

    def hide_top(self):
        self.cancel_top_hide()
        self.top_revealed = False
        self.top_bar.hide()
        self.title_strip.set_visible(False)


class DockApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="os.glass.Dock", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.dock = Dock(self)
        self.dock.present()


if __name__ == "__main__":
    sys.exit(DockApp().run(sys.argv))
