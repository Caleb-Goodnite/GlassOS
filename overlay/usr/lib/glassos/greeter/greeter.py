#!/usr/bin/python3
"""GlassOS login screen - a greeter for greetd.

Runs as the greeter user inside the tiny "cage" compositor. It talks to greetd over the
socket in $GREETD_SOCK (length-prefixed JSON). Your password goes straight to greetd/PAM;
the greeter keeps no copy. It saves one thing: which user logged in last.
Run without $GREETD_SOCK to preview it (any password works).
"""
import json
import os
import pwd
import socket
import struct
import subprocess
import sys
import threading
import time

os.environ.setdefault("XDG_CACHE_HOME", "/tmp/glass-greeter-cache")
sys.path.insert(0, "/usr/lib/glassos")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

import glassui as ui  # noqa: E402

WALLPAPER = "/usr/share/glassos/wallpapers/prism.jpg"
LAST_USER = "/var/cache/glass-greeter/last-user"
# tells the glass-greeter wrapper a session was started (otherwise it falls back to the text login)
OK_MARK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "glass-greeter.ok")
SESSION = ["glass-session"]

CSS = """
window.greeter { background: #0b0c14; color: #fff; }
.time { font-size: 104px; font-weight: 700; letter-spacing: -2px; font-feature-settings: "tnum";
        color: alpha(#ffffff, 0.92); text-shadow: 0 2px 24px alpha(#000000, 0.25); }
.date { font-size: 21px; font-weight: 600; color: alpha(#ffffff, 0.85); }
.avatar { min-width: 96px; min-height: 96px; border-radius: 99px; font-size: 38px; font-weight: 700;
          background: alpha(#ffffff, 0.18); border: 1px solid alpha(#ffffff, 0.35); }
.who { font-size: 20px; font-weight: 700; text-shadow: 0 1px 8px alpha(#000000, 0.3); }
entry.pw { min-width: 260px; min-height: 38px; border-radius: 99px; padding: 0 6px 0 16px;
           background: alpha(#ffffff, 0.16); border: 1px solid alpha(#ffffff, 0.28);
           box-shadow: inset 0 1px alpha(#ffffff, 0.15), 0 8px 24px alpha(#000000, 0.18); color: #fff; }
entry.pw:focus-within { background: alpha(#ffffff, 0.22); border-color: alpha(#ffffff, 0.5); }
.hint { font-size: 13px; color: alpha(#ffffff, 0.7); }
.err { color: #ffc2c2; }
button.glassbtn { border-radius: 99px; min-width: 44px; min-height: 44px; padding: 0;
                  background: alpha(#ffffff, 0.13); border: 1px solid alpha(#ffffff, 0.22); color: #fff;
                  box-shadow: none; }
button.glassbtn:hover { background: alpha(#ffffff, 0.24); }
button.glassbtn:active { background: alpha(#ffffff, 0.32); }
button.glassbtn:focus-visible, button.userbtn:focus-visible { outline: 2px solid #ffffff; outline-offset: 2px; }
button.glassbtn:disabled { opacity: 0.5; }
/* the one accent on this screen: the button that logs you in */
button.go { background: alpha(#3d6fd1, 0.85); border-color: alpha(#ffffff, 0.3); }
button.go:hover { background: alpha(#4a7fe6, 0.95); }
button.userbtn { border-radius: 99px; padding: 4px 14px; background: alpha(#ffffff, 0.08);
                 border: 1px solid alpha(#ffffff, 0.16); color: #fff; box-shadow: none; }
.caption { font-size: 12px; color: alpha(#ffffff, 0.75); }
.brand { font-size: 13px; font-weight: 700; color: alpha(#ffffff, 0.7); }
"""


class Greetd:
    """Minimal greetd IPC client."""

    def __init__(self):
        self.path = os.environ.get("GREETD_SOCK")
        self.sock = None

    def _call(self, msg):
        if self.sock is None:
            self.sock = socket.socket(socket.AF_UNIX)
            self.sock.connect(self.path)
        data = json.dumps(msg).encode()
        self.sock.sendall(struct.pack("=I", len(data)) + data)
        hdr = self._recv(4)
        (n,) = struct.unpack("=I", hdr)
        return json.loads(self._recv(n))

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("greetd closed the connection")
            buf += chunk
        return buf

    def login(self, user, password):
        """Returns None on success (session will start when we exit), or an error message."""
        if not self.path:  # preview mode
            time.sleep(0.6)
            return None
        try:
            r = self._call({"type": "create_session", "username": user})
            while r.get("type") == "auth_message":
                if r.get("auth_message_type") in ("secret", "visible"):
                    r = self._call({"type": "post_auth_message_response", "response": password})
                else:
                    r = self._call({"type": "post_auth_message_response"})
            if r.get("type") != "success":
                self._call({"type": "cancel_session"})
                return "Wrong password. Try again." if r.get("error_type") == "auth_error" else \
                    (r.get("description") or "Couldn't log in.")
            r = self._call({"type": "start_session", "cmd": SESSION, "env": []})
            if r.get("type") != "success":
                self._call({"type": "cancel_session"})
                return r.get("description") or "Couldn't start the desktop."
            return None
        except Exception as e:
            try:
                self.sock and self.sock.close()
            finally:
                self.sock = None
            return f"Login service problem: {e}"


def people():
    users = []
    for p in pwd.getpwall():
        if 1000 <= p.pw_uid < 60000 and not p.pw_shell.endswith(("nologin", "false")):
            users.append(p)
    try:
        last = open(LAST_USER).read().strip()
    except OSError:
        last = ""
    users.sort(key=lambda p: (p.pw_name != last, p.pw_name))
    return users


def blurred_wallpaper(width=1920, height=1080):
    """A soft frosted copy of the wallpaper: shrink it a lot, then scale back up smoothly."""
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(WALLPAPER)
    except GLib.Error:
        return None
    small = pb.scale_simple(max(8, pb.get_width() // 40), max(8, pb.get_height() // 40),
                            GdkPixbuf.InterpType.HYPER)
    mid = small.scale_simple(small.get_width() * 4, small.get_height() * 4, GdkPixbuf.InterpType.BILINEAR)
    big = mid.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
    return Gdk.Texture.new_for_pixbuf(big)


class Greeter(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="GlassOS")
        self.add_css_class("greeter")
        self.greetd = Greetd()
        self.users = people()
        self.idx = 0

        overlay = Gtk.Overlay()
        tex = blurred_wallpaper()
        if tex:
            bg = Gtk.Picture.new_for_paintable(tex)
            bg.set_content_fit(Gtk.ContentFit.COVER)
            bg.set_can_shrink(True)
            overlay.set_child(bg)
        else:
            overlay.set_child(Gtk.Box())

        # clock
        top = ui.vbox(0)
        top.set_halign(Gtk.Align.CENTER)
        top.set_valign(Gtk.Align.START)
        top.set_margin_top(70)
        self.date = ui.label("", "date", xalign=0.5)
        self.time = ui.label("", "time", xalign=0.5)
        top.append(self.date)
        top.append(self.time)
        overlay.add_overlay(top)

        # who + password
        mid = ui.vbox(12)
        mid.set_halign(Gtk.Align.CENTER)
        mid.set_valign(Gtk.Align.END)
        mid.set_margin_bottom(130)
        self.avatar = ui.label("", "avatar", xalign=0.5)
        self.avatar.set_halign(Gtk.Align.CENTER)
        mid.append(self.avatar)
        self.who = ui.label("", "who", xalign=0.5)
        mid.append(self.who)
        row = ui.hbox(8)
        row.set_halign(Gtk.Align.CENTER)
        self.pw = Gtk.PasswordEntry(show_peek_icon=True)
        self.pw.add_css_class("pw")
        self.pw.set_property("placeholder-text", "Enter Password")
        self.pw.connect("activate", lambda *_: self.submit())
        row.append(self.pw)
        self.go = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self.go.add_css_class("glassbtn")
        self.go.add_css_class("go")
        self.go.set_tooltip_text("Log in")
        self.go.connect("clicked", lambda *_: self.submit())
        row.append(self.go)
        mid.append(row)
        self.hint = ui.label("", "hint", xalign=0.5)
        mid.append(self.hint)
        if len(self.users) > 1:
            sw = Gtk.Button(label="Switch user")
            sw.add_css_class("userbtn")
            sw.set_halign(Gtk.Align.CENTER)
            sw.connect("clicked", lambda *_: self.next_user())
            mid.append(sw)
        overlay.add_overlay(mid)

        # bottom: brand + power
        bottom = ui.hbox(18)
        bottom.set_valign(Gtk.Align.END)
        bottom.set_margin_bottom(26)
        bottom.set_margin_start(30)
        bottom.set_margin_end(30)
        brand = ui.hbox(8)
        logo = Gtk.Image.new_from_file("/usr/share/glassos/logo-symbolic.png")
        logo.set_pixel_size(16)
        brand.append(logo)
        brand.append(ui.label("GlassOS", "brand"))
        brand.set_valign(Gtk.Align.END)
        bottom.append(brand)
        bottom.append(ui.spacer())
        for icon, text, cmd in (("system-reboot-symbolic", "Restart", ["systemctl", "reboot"]),
                                ("system-shutdown-symbolic", "Shut Down", ["systemctl", "poweroff"])):
            col = ui.vbox(6)
            b = Gtk.Button.new_from_icon_name(icon)
            b.add_css_class("glassbtn")
            b.set_halign(Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, c=cmd: subprocess.Popen(c))
            col.append(b)
            col.append(ui.label(text, "caption", xalign=0.5))
            bottom.append(col)
        overlay.add_overlay(bottom)

        self.set_child(overlay)
        self.show_user()
        self.tick()
        GLib.timeout_add(1000, self.tick)
        self.fullscreen()
        GLib.idle_add(self.focus_password)

    def focus_password(self):
        # Runs once. (Passing grab_focus straight to idle_add repeats it forever, because it
        # returns True, and each call selects the whole field, so every key replaced the last.)
        self.pw.grab_focus()
        return False

    def tick(self):
        self.time.set_text(time.strftime("%-I:%M"))
        self.date.set_text(time.strftime("%A, %B %-d"))
        return True

    def show_user(self):
        if not self.users:
            self.who.set_text("No user accounts")
            self.pw.set_sensitive(False)
            return
        u = self.users[self.idx]
        name = (u.pw_gecos.split(",")[0] or u.pw_name).strip()
        initials = "".join(w[0] for w in name.split()[:2]).upper() or u.pw_name[:1].upper()
        self.avatar.set_text(initials)
        self.who.set_text(name)
        self.hint.remove_css_class("err")
        self.hint.set_text("")

    def next_user(self):
        self.idx = (self.idx + 1) % len(self.users)
        self.show_user()
        self.pw.set_text("")
        self.pw.grab_focus()

    def submit(self):
        if not self.users or not self.pw.get_sensitive():
            return
        user = self.users[self.idx].pw_name
        password = self.pw.get_text()
        self.pw.set_sensitive(False)
        self.go.set_sensitive(False)
        self.hint.remove_css_class("err")
        self.hint.set_text("Logging in…")

        def work():
            err = self.greetd.login(user, password)
            GLib.idle_add(self.done, user, err)

        threading.Thread(target=work, daemon=True).start()

    def done(self, user, err):
        if err is None:
            try:
                open(OK_MARK, "w").close()
            except OSError:
                pass
            try:
                os.makedirs(os.path.dirname(LAST_USER), exist_ok=True)
                with open(LAST_USER, "w") as f:
                    f.write(user)
            except OSError:
                pass
            self.get_application().quit()   # greetd starts your desktop as soon as we exit
            return False
        self.hint.add_css_class("err")
        self.hint.set_text(err)
        self.pw.set_text("")
        self.pw.set_sensitive(True)
        self.go.set_sensitive(True)
        self.pw.grab_focus()
        return False


class GreeterApp(Gtk.Application):
    def __init__(self):
        # no application id: the login screen has no D-Bus session to register on
        super().__init__(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        st = Gtk.Settings.get_default()
        st.set_property("gtk-icon-theme-name", "Papirus-Dark")
        st.set_property("gtk-font-name", "Inter 11")
        st.set_property("gtk-application-prefer-dark-theme", True)
        ui.apply_css(CSS)
        Greeter(self).present()


if __name__ == "__main__":
    sys.exit(GreeterApp().run([sys.argv[0]]))
