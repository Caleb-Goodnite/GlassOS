#!/usr/bin/python3
"""GlassOS Dock - a frosted-glass dock for pinned and running apps.

Left-click: open the app (or bring its window forward if it's already running).
Right-click: new window / close / keep in dock.
Pinned apps are listed in ~/.config/glassos/dock.conf.
"""
import json
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


def dock_icon_size():
    try:
        with open(APPEARANCE) as f:
            return SIZES.get(json.load(f).get("dock_size"), SIZES["medium"])
    except (OSError, ValueError, AttributeError):
        return SIZES["medium"]

CSS = b"""
window.glass-dock { background: transparent; }
.dock {
  background: alpha(#ffffff, 0.12);
  border: 1px solid alpha(#ffffff, 0.18);
  border-top-color: alpha(#ffffff, 0.42);
  border-radius: 26px;
  padding: 6px 8px 3px 8px;
  margin: 22px 16px 10px 16px;
  box-shadow: inset 0 1px 1px alpha(#ffffff, 0.16);   /* no outer shadow: it would be clipped into a box at the surface edge */
}
.dock-item {
  background: none;
  border: none;
  box-shadow: none;
  padding: 3px 4px 0 4px;
  margin: 0 1px;
  border-radius: 16px;
  transition: transform 220ms cubic-bezier(0.2, 0.9, 0.25, 1.25), background 160ms ease;
}
.dock-item:hover {
  transform: translateY(-7px) scale(1.18);
}
.dock-item:active { transform: translateY(-3px) scale(1.06); }
.dot {
  min-width: 5px; min-height: 5px; border-radius: 3px;
  margin-top: 3px; margin-bottom: 2px;
  background: transparent;
}
.dot.running { background: alpha(#ffffff, 0.9); box-shadow: 0 0 4px alpha(#ffffff, 0.6); }
.dot.focused { background: #ffffff; min-width: 12px; }
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
                    if ev in ("openwindow", "closewindow", "activewindowv2", "movewindowv2", "windowtitlev2"):
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
        self.dot = Gtk.Box()
        self.dot.add_css_class("dot")
        self.dot.set_halign(Gtk.Align.CENTER)
        box.append(icon)
        box.append(self.dot)
        self.set_child(box)
        self.set_tooltip_text(name or (info.get_display_name() if info else app_id))
        self.connect("clicked", self.on_click)
        rc = Gtk.GestureClick(button=3)
        rc.connect("pressed", self.on_right_click)
        self.add_controller(rc)

    def set_windows(self, wins, active):
        self.windows = wins
        self.dot.remove_css_class("running")
        self.dot.remove_css_class("focused")
        if wins:
            self.dot.add_css_class("running")
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
        self.apply_size()
        # Settings saves appearance.json; pick up a new dock size straight away
        self.appearance_mon = Gio.File.new_for_path(APPEARANCE).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.appearance_mon.connect("changed", lambda *_a: self.apply_size() if dock_icon_size() != ICON_SIZE else None)
        self.refresh()
        listen_events(self.refresh)
        GLib.timeout_add_seconds(3, self.refresh)  # safety net
        Gio.AppInfoMonitor.get().connect("changed", lambda *_: self.rebuild())

    def apply_size(self):
        global ICON_SIZE
        ICON_SIZE = dock_icon_size()
        css = f".dock {{ border-radius: {round((ICON_SIZE + 22) * 0.38)}px; }}"
        if hasattr(self.size_css, "load_from_string"):
            self.size_css.load_from_string(css)
        else:
            self.size_css.load_from_data(css.encode())
        # the bar is the icon plus 22 px of padding and dots, with 10 px under it; windows that
        # are maximized or tiled stop above it
        Layer.set_exclusive_zone(self, ICON_SIZE + 28)
        if self.items:
            self.rebuild()

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
                            gicon=Gio.ThemedIcon.new_from_names(["view-app-grid", "applications-all",
                                                                 "view-grid", "applications-other"]),
                            name="All Apps (Super+Space)",
                            action=lambda: subprocess.Popen(["sh", "-c", "glass-sound launcher; fuzzel"]))
            self.box.append(apps)
            self.items["glass:apps"] = apps

        for k, it in self.items.items():
            it.set_windows(running.get(k, [None, []])[1], active)
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
