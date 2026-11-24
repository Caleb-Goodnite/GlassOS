#!/usr/bin/python3
"""GlassOS Dock - a frosted-glass dock for pinned and running apps.

Left-click: open the app (or bring its window forward if it's already running).
Right-click: new window / close / keep in dock.
Pinned apps are listed in ~/.config/glassos/dock.conf.

Pointing at the dock magnifies the icons near the pointer, like a Mac. While a window is full
size (or when "Hide the dock automatically" is on), the dock gets out of the way and comes back
up when the pointer touches the bottom edge of the screen.
"""
import json
import math
import os
import shlex
import socket
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as Layer  # noqa: E402

CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "glassos", "dock.conf")
APPEARANCE = os.path.join(os.path.dirname(CONF), "appearance.json")   # Settings > Appearance > Dock size
SIZES = {"small": 30, "medium": 36, "large": 46}                       # icon size in pixels
ICON_SIZE = SIZES["medium"]
MAX_MAGNIFIED = 128                     # px: magnification never draws an icon bigger than this
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


def dock_magnification(a=None):
    """How big the icon under the pointer grows: 1 (off) to 2 (twice the size)."""
    a = appearance() if a is None else a
    try:
        v = max(0.0, min(100.0, float(a.get("dock_magnify", 50))))
    except (TypeError, ValueError):
        v = 50.0
    return 1.0 + v / 100.0


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
  transition: transform 110ms ease-out;
}
/* magnification (Dock.magnify sets each icon's size and the push sideways) */
.dock-item image { transform-origin: 50% 100%; transition: transform 110ms ease-out; }
.dock-item:active image { opacity: 0.8; }
.dock { transition: padding 110ms ease-out, transform 240ms cubic-bezier(0.2, 0.9, 0.3, 1); }
.dock.settle, .dock.settle .dock-item, .dock.settle .dock-item image { transition-duration: 260ms; }
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
.dock-sep { min-width: 1px; background: alpha(#ffffff, 0.25); margin: 10px 7px 12px 7px; transition: transform 110ms ease-out; }
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
        """The app's name, floating above the magnified icon like on a Mac. (A tooltip would sit
        on top of the icon: GTK places it against the unmagnified button.)"""
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
            rise = round(ICON_SIZE * (self.dock.magnify_max - 1)) + 6
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


class Dock(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.add_css_class("glass-dock")
        self.set_decorated(False)
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
        # magnification: rewritten as the pointer moves, so it sits above everything else
        self.mag_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.mag_css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        self.magnify_max = dock_magnification()
        self.pointer = None          # pointer x in the bar's coordinates, while it's over the dock
        self.mag_pending = False
        self.mag_active = False
        # whether the pointer is anywhere on the dock (for hiding)...
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self.on_enter)
        motion.connect("leave", self.on_leave)
        self.add_controller(motion)
        # ...and where it is along the bar, in the bar's own coordinates (the icons' too)
        along = Gtk.EventControllerMotion()
        along.connect("enter", self.on_motion)
        along.connect("motion", self.on_motion)
        along.connect("leave", self.on_bar_leave)
        self.box.add_controller(along)
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
        self.magnify_max = min(dock_magnification(a), max(1.0, MAX_MAGNIFIED / ICON_SIZE))
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
        # room above the bar for magnified icons to grow into
        headroom = max(22, round(ICON_SIZE * (self.magnify_max - 1)) + 10)
        css = (f".dock {{ border-radius: {round((ICON_SIZE + 22) * 0.38)}px; margin-top: {headroom}px; "
               f"background-image: linear-gradient(180deg, alpha(#ffffff, {top:.3f}), alpha(#ffffff, {bottom:.3f})); }}"
               f".dock.tucked {{ transform: translateY({ICON_SIZE + 60}px); }}")
        if hasattr(self.size_css, "load_from_string"):
            self.size_css.load_from_string(css)
        else:
            self.size_css.load_from_data(css.encode())
        # the bar is the icon plus 22 px of padding and dots, with 10 px under it; windows that
        # are maximized or tiled stop above it
        self.set_exclusive()
        if rebuild and self.items:
            self.rebuild()

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
        if fs != self.fullscreen:
            self.fullscreen = fs
            self.update_hidden_mode()
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
            for i, it in enumerate(self.items.values()):   # names the magnification rules use
                it.set_name(f"di{i}")
                it.icon.set_name(f"dim{i}")
            self.queue_magnify()

        for k, it in self.items.items():
            it.set_windows(running.get(k, [None, []])[1], active)
        return True


    # ------------------------------------------------------------------------- magnification
    def on_enter(self, _c, _x, _y):
        self.hovering = True
        self.cancel_hide()

    def on_motion(self, _c, x, _y):
        self.pointer = x
        self.queue_magnify()

    def on_bar_leave(self, _c):
        self.pointer = None
        self.queue_magnify()

    def on_leave(self, _c):
        self.hovering = False
        self.pointer = None
        self.queue_magnify()
        if self.hidden_mode:
            self.schedule_hide()

    def queue_magnify(self):
        if not self.mag_pending:   # at most once per frame
            self.mag_pending = True
            self.add_tick_callback(lambda *_: self.magnify())

    def magnify(self):
        """Grow the icons near the pointer, push their neighbours aside and widen the bar to fit,
        like the Dock on a Mac. Sizes fall off along a cosine about two and a half icons wide."""
        self.mag_pending = False
        items = list(self.items.values())
        px = self.pointer if self.magnify_max > 1.01 else None
        rules = []
        pad = 0.0
        if px is not None and items:
            # where each icon sits with no magnification: the bar lays its children out in a row,
            # and its coordinates start inside its padding, so the widening doesn't move them
            # (the dividers move aside with the icons, but don't grow)
            kids, centers, x, seps = [], [], 0.0, 0
            child = self.box.get_first_child()
            while child:
                w = child.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
                if not isinstance(child, DockItem):
                    child.set_name(f"ds{seps}")
                    seps += 1
                kids.append(child)
                centers.append(x + w / 2)
                x += w
                child = child.get_next_sibling()
            slot = ICON_SIZE + 10
            reach = slot * 2.6
            scale = []
            for k, c in zip(kids, centers):
                d = abs(px - c)
                f = (1 + math.cos(math.pi * d / reach)) / 2 if d < reach and isinstance(k, DockItem) else 0.0
                scale.append(1 + (self.magnify_max - 1) * f)
            extra = [ICON_SIZE * (sc - 1) for sc in scale]
            # each icon's growth pushes the others away from it; the spot under the pointer stays put
            shift = []
            for i, ci in enumerate(centers):
                dx = 0.0
                for j, cj in enumerate(centers):
                    if j != i:
                        dx += extra[j] * 0.5 * (1 if ci > cj else -1)
                    dx -= extra[j] * 0.5 * max(-1.0, min(1.0, (px - cj) / (slot / 2)))
                shift.append(dx)
            left = max(0.0, -(shift[0] - extra[0] / 2))
            right = max(0.0, shift[-1] + extra[-1] / 2)
            pad = max(left, right)
            for k, sc, dx in zip(kids, scale, shift):
                rules.append(f"#{k.get_name()} {{ transform: translateX({dx:.1f}px); }}")
                if isinstance(k, DockItem):
                    rules.append(f"#{k.icon.get_name()} {{ transform: scale({sc:.3f}); }}")
        active = bool(rules)
        if active != self.mag_active:
            self.mag_active = active
            # settling back after the pointer leaves is a little slower than following it
            (self.box.remove_css_class if active else self.box.add_css_class)("settle")
        rules.append(f".dock {{ padding-left: {8 + pad:.1f}px; padding-right: {8 + pad:.1f}px; }}")
        css = "\n".join(rules)
        if hasattr(self.mag_css, "load_from_string"):
            self.mag_css.load_from_string(css)
        else:
            self.mag_css.load_from_data(css.encode())
        return False

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
                if y >= my + h - 3:
                    self.cancel_hide()
                    if not self.revealed:
                        self.show_now()
                elif (self.revealed and not self.hovering and not self.menus and not self.hide_id
                      and y < my + h - (ICON_SIZE + 40)):
                    self.schedule_hide(250)
                break
        return True


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
