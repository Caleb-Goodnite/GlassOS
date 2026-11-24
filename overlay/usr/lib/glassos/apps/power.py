#!/usr/bin/env python3
"""GlassOS power dialog: shut down, restart or log out, with a 60-second countdown.

  glass-power [shutdown|restart|logout]

Opened by Super+Option+Delete (Super+Alt+Backspace on a PC keyboard) and by the GlassOS menu.
Nothing happens straight away: the chosen action runs when the countdown ends, or when you
click its button. Cancel (or Esc, or a click outside the dialog) closes it.
"""
import os
import subprocess
import sys

sys.path.insert(0, "/usr/lib/glassos")
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as Layer  # noqa: E402
except (ValueError, ImportError):
    Layer = None
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

import glassui as ui  # noqa: E402

SECONDS = 60
MODES = {
    "shutdown": ("Shut down this computer?", "GlassOS will shut down in {n} seconds.", "Shut Down",
                 "system-shutdown-symbolic"),
    "restart": ("Restart this computer?", "GlassOS will restart in {n} seconds.", "Restart",
                "system-reboot-symbolic"),
    "logout": ("Log out?", "You'll be logged out in {n} seconds.", "Log Out", "system-log-out-symbolic"),
}

CSS = """
window.power { background: alpha(#05060c, 0.45); }
.power-card {
  background: alpha(#10111a, 0.78);
  border: 1px solid alpha(#ffffff, 0.12);
  border-top-color: alpha(#ffffff, 0.26);
  border-radius: 22px;
  padding: 28px 30px 22px 30px;
  box-shadow: 0 24px 60px alpha(#000000, 0.45);
}
.power-icon { color: #ffffff; }
.power-title { font-size: 21px; font-weight: 800; }
.power-sub { color: alpha(#ffffff, 0.86); font-feature-settings: "tnum"; }
.power-note { color: alpha(#ffffff, 0.85); font-size: 12px; }
.power-card button { min-height: 40px; padding: 0 18px; border-radius: 99px; }
.power-card button.link { min-height: 30px; padding: 0 10px; background: transparent; color: alpha(#ffffff, 0.86); }
.power-card button.link:hover { color: #ffffff; background: alpha(#ffffff, 0.08); }
"""


def run_action(mode):
    if mode == "shutdown":
        subprocess.run(["glass-sound", "shutdown", "--wait"])
        subprocess.Popen(["systemctl", "poweroff"])
    elif mode == "restart":
        subprocess.run(["glass-sound", "reboot", "--wait"])
        subprocess.Popen(["systemctl", "reboot"])
    elif mode == "logout":
        subprocess.run(["glass-sound", "logout", "--wait"])
        subprocess.Popen(["hyprctl", "dispatch", "hl.dsp.exit()"])
    elif mode == "lock":
        subprocess.Popen(["glass-lock"], start_new_session=True)


class PowerWindow(Gtk.ApplicationWindow):
    def __init__(self, app, mode):
        super().__init__(application=app, title="Power")
        self.add_css_class("power")
        self.set_decorated(False)
        if Layer and Layer.is_supported():
            Layer.init_for_window(self)
            Layer.set_namespace(self, "glass-power")
            Layer.set_layer(self, Layer.Layer.OVERLAY)
            for e in (Layer.Edge.TOP, Layer.Edge.BOTTOM, Layer.Edge.LEFT, Layer.Edge.RIGHT):
                Layer.set_anchor(self, e, True)
            Layer.set_exclusive_zone(self, -1)
            Layer.set_keyboard_mode(self, Layer.KeyboardMode.EXCLUSIVE)
        else:
            self.fullscreen()

        # a click on the dimmed area outside the dialog cancels
        outside = Gtk.GestureClick()
        outside.connect("released", self.on_outside)
        self.add_controller(outside)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)

        self.card = ui.vbox(10, "power-card")
        self.card.set_halign(Gtk.Align.CENTER)
        self.card.set_valign(Gtk.Align.CENTER)
        self.card.set_size_request(420, -1)
        inside = Gtk.GestureClick()
        inside.connect("released", lambda g, *a: g.set_state(Gtk.EventSequenceState.CLAIMED))
        self.card.add_controller(inside)

        self.icon = Gtk.Image()
        self.icon.set_pixel_size(40)
        self.icon.add_css_class("power-icon")
        self.card.append(self.icon)
        self.title = ui.label("", "power-title", xalign=0.5)
        self.card.append(self.title)
        self.sub = ui.label("", "power-sub", xalign=0.5)
        self.card.append(self.sub)
        self.card.append(ui.label("Open apps are closed, so save your work first.", "power-note", xalign=0.5))

        row = ui.hbox(10)
        row.set_halign(Gtk.Align.CENTER)
        row.set_margin_top(12)
        self.cancel = ui.button("Cancel", self.close_now, "pill")
        row.append(self.cancel)
        self.alt = ui.button("", self.on_alt, "pill")
        row.append(self.alt)
        self.go = ui.button("", lambda: self.finish(self.mode), "pill accent")
        row.append(self.go)
        self.card.append(row)

        links = ui.hbox(4)
        links.set_halign(Gtk.Align.CENTER)
        for text, m in (("Lock", "lock"), ("Log Out", "logout")):
            b = ui.button(text, lambda m=m: self.finish(m) if m == "lock" else self.set_mode(m), "link")
            links.append(b)
        self.card.append(links)

        overlay = Gtk.Overlay()
        overlay.set_child(Gtk.Box(hexpand=True, vexpand=True))
        overlay.add_overlay(self.card)
        self.set_child(overlay)
        self.set_mode(mode)
        GLib.timeout_add_seconds(1, self.tick)
        self.cancel.grab_focus()

    def set_mode(self, mode):
        self.mode = mode
        self.left = SECONDS
        title, sub, go, icon = MODES[mode]
        self.title.set_text(title)
        self.sub_fmt = sub
        self.sub.set_text(sub.format(n=self.left))
        self.go.set_label(go)
        self.icon.set_from_icon_name(icon)
        # the middle button offers the other of shut down / restart
        self.alt.set_label("Restart" if mode == "shutdown" else "Shut Down")
        self.alt.set_visible(mode != "logout")

    def on_alt(self):
        self.finish("restart" if self.mode == "shutdown" else "shutdown")

    def tick(self):
        self.left -= 1
        if self.left <= 0:
            self.finish(self.mode)
            return False
        self.sub.set_text(self.sub_fmt.format(n=self.left))
        return True

    def finish(self, mode):
        self.set_visible(False)
        # let the dialog disappear before the sound plays and the session ends
        GLib.timeout_add(150, lambda: (run_action(mode), self.get_application().quit()) and False)

    def close_now(self):
        self.get_application().quit()

    def on_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.close_now()
            return True
        return False

    def on_outside(self, gesture, _n, x, y):
        ok, bounds = self.card.compute_bounds(self)
        if ok and not (bounds.get_x() <= x <= bounds.get_x() + bounds.get_width()
                       and bounds.get_y() <= y <= bounds.get_y() + bounds.get_height()):
            self.close_now()


class PowerApp(Gtk.Application):
    def __init__(self, mode):
        super().__init__(application_id="os.glass.Power", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.mode = mode

    def do_activate(self):
        ui.apply_css()
        prov = Gtk.CssProvider()
        if hasattr(prov, "load_from_string"):
            prov.load_from_string(CSS)
        else:
            prov.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        PowerWindow(self, self.mode).present()


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in MODES else "shutdown"
    # only one power dialog at a time
    lock = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "glass-power.pid")
    try:
        old = int(open(lock).read())
        os.kill(old, 0)
        sys.exit(0)
    except (OSError, ValueError):
        pass
    with open(lock, "w") as f:
        f.write(str(os.getpid()))
    try:
        PowerApp(m).run([sys.argv[0]])
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass
