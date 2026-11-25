#!/usr/bin/python3
"""Glass Panel - the drop-downs under the top bar's icons.

  glass-panel wifi       Wi-Fi on/off, the network you're on, known networks, other networks
  glass-panel bluetooth  Bluetooth on/off and your devices
  glass-panel sound      volume, and which speakers or headphones to use
  glass-panel control    Control Centre, laid out like macOS's: Wi-Fi and Bluetooth, Focus (Do Not
                         Disturb), Capture and Settings tiles, brightness and volume sliders, Now Playing
  glass-panel window     the focused window: Close, Minimize, Full Size, Center (the top bar's app name)

It opens under the mouse pointer and closes when you click anywhere else or press Escape.
Nothing runs in the background: it reads the current state when it opens, and quits when it closes.
"""
import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, "/usr/lib/glassos")
import glasshw as hw  # noqa: E402
import glassui as ui  # noqa: E402
from glassui import hbox, label, vbox  # noqa: E402
import gi  # noqa: E402

gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as Layer  # noqa: E402

APP_ID = "os.glass.Panel"
WIDTH = 320
CC_WIDTH = 340      # the Control Centre is a little wider, for its two columns of modules
SINK = "@DEFAULT_AUDIO_SINK@"


def css():
    a = ui.appearance()
    look = ui.glass_look(a["glass"])
    acc = a["accent"]
    # a menu sits over anything, so it is always a little more opaque than a window
    return f"""
window.panel-win {{ background: transparent; }}
/* the click-away sheet: Hyprland sends no clicks to a surface that is completely see-through */
window.catcher {{ background: alpha(#000000, 0.01); }}
.menu {{ background-color: alpha({look["tint_rgb"]}, {min(0.92, look["tint"] + 0.22):.2f}); color: #f4f5fa;
        border-radius: 16px; padding: 8px 6px; margin: 2px 4px 10px 4px;
        {ui.glass_edges(top=0.30, bottom=0.12, side=0.12, sheen=0.12, edge=0.16)} }}
.menu label {{ text-shadow: none; }}
.menu-title {{ font-weight: 700; font-size: 14px; }}
.menu-head {{ font-weight: 700; font-size: 12px; color: alpha(#ffffff, 0.62); margin: 8px 10px 2px 10px; }}
.menu-pad {{ padding: 4px 10px; }}
.menu-sep {{ min-height: 1px; background: alpha(#ffffff, 0.10); margin: 6px 10px; }}
button.item {{ background: none; border: none; box-shadow: none; border-radius: 9px; padding: 5px 8px;
              color: #fff; min-height: 0; }}
button.item:hover {{ background: alpha(#ffffff, 0.09); }}
button.item:active {{ background: alpha(#ffffff, 0.14); }}
.dot {{ min-width: 26px; min-height: 26px; border-radius: 99px; background: alpha(#ffffff, 0.14); }}
.dot.on {{ background-image: linear-gradient(180deg, alpha({acc}, 1.0), alpha({acc}, 0.82)); }}
button.dot-btn {{ min-width: 30px; min-height: 30px; padding: 0; border-radius: 99px; border: none;
                 background: alpha(#ffffff, 0.14); box-shadow: inset 0 1px alpha(#ffffff, 0.12); color: #fff; }}
button.dot-btn:hover {{ background: alpha(#ffffff, 0.22); }}
button.dot-btn.on {{ background-image: linear-gradient(180deg, alpha({acc}, 1.0), alpha({acc}, 0.82)); }}
.tile {{ border-radius: 14px; padding: 8px 6px; margin: 3px 4px;
        background-image: linear-gradient(180deg, alpha(#ffffff, 0.09), alpha(#ffffff, 0.05));
        {ui.glass_edges(top=0.20, bottom=0.08, side=0.06, sheen=0.08, edge=0.10)} }}
.sub {{ font-size: 12px; color: alpha(#ffffff, 0.68); }}
/* Control Centre: a grid of glass modules, like macOS */
.menu.cc {{ padding: 10px; }}
.cc-tile {{ border-radius: 16px; padding: 8px;
           background-image: linear-gradient(180deg, alpha(#ffffff, 0.11), alpha(#ffffff, 0.06));
           {ui.glass_edges(top=0.22, bottom=0.08, side=0.07, sheen=0.08, edge=0.10)} }}
.cc-name {{ font-weight: 600; font-size: 13px; }}
.cc-sub {{ font-size: 11px; color: alpha(#ffffff, 0.60); }}
.cc-small-name {{ font-size: 11px; font-weight: 600; }}
button.cc-round {{ min-width: 32px; min-height: 32px; padding: 0; border-radius: 99px; border: none;
                  background: alpha(#ffffff, 0.16); box-shadow: inset 0 1px alpha(#ffffff, 0.12); color: #fff; }}
button.cc-round:hover {{ background: alpha(#ffffff, 0.24); }}
button.cc-round.on {{ background-image: linear-gradient(180deg, alpha({acc}, 1.0), alpha({acc}, 0.85)); }}
button.cc-cell {{ background: none; border: none; box-shadow: none; border-radius: 11px; padding: 4px;
                 color: #fff; min-height: 0; }}
button.cc-cell:hover {{ background: alpha(#ffffff, 0.08); }}
button.cc-cell:active {{ background: alpha(#ffffff, 0.13); }}
button.cc-cell:disabled {{ opacity: 0.45; }}
.cc-art {{ min-width: 40px; min-height: 40px; border-radius: 9px; color: #fff;
          background-image: linear-gradient(160deg, alpha({acc}, 0.95), alpha({acc}, 0.45)); }}
button.cc-media {{ background: none; border: none; box-shadow: none; min-width: 30px; min-height: 30px;
                  padding: 0; border-radius: 99px; color: #fff; }}
button.cc-media:hover {{ background: alpha(#ffffff, 0.10); }}
/* the fat pill slider: white fill, white knob, a grey symbol riding in the knob's end */
scale.pill {{ padding: 0; margin: 2px 0 0 0; }}
scale.pill trough {{ min-height: 24px; border-radius: 99px; padding: 0; border: none; outline: none;
                    background: alpha(#ffffff, 0.16); box-shadow: inset 0 1px 2px alpha(#000000, 0.25); }}
scale.pill highlight {{ min-height: 24px; border-radius: 99px; border: none; background: #ffffff; }}
scale.pill slider {{ min-width: 24px; min-height: 24px; margin: 0; padding: 0; border-radius: 99px;
                    border: none; outline: none; background: #ffffff; box-shadow: 0 0 4px alpha(#000000, 0.35); }}
scale.pill:disabled trough {{ opacity: 0.5; }}
.pill-icon {{ color: alpha(#000000, 0.55); }}
.warn {{ color: #ffd479; }}
.menu entry {{ border-radius: 9px; }}
"""


def bg(fn, done=None):
    """Run fn() in a thread, then done(result) on the UI thread."""
    def work():
        try:
            res = fn()
        except Exception as e:
            res = e
        if done:
            GLib.idle_add(lambda: (done(res), False)[1])
    threading.Thread(target=work, daemon=True).start()


def spawn(argv):
    try:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def icon(name, size=16):
    im = Gtk.Image.new_from_icon_name(name)
    im.set_pixel_size(size)
    return im


def dot(icon_name, on=False):
    """A round badge with a small icon in the middle (accent-coloured when on)."""
    d = icon(icon_name, 14)
    d.set_valign(Gtk.Align.CENTER)
    d.add_css_class("dot")
    if on:
        d.add_css_class("on")
    return d


def item(cb, *children, sub=None):
    """A clickable menu line: children laid out left to right; the first label grows."""
    b = Gtk.Button()
    b.add_css_class("item")
    row = hbox(10)
    for c in children:
        if isinstance(c, str):
            t = vbox(0)
            t.set_hexpand(True)
            t.set_valign(Gtk.Align.CENTER)
            t.append(label(c, ellipsize=True))
            if sub:
                t.append(label(sub, "sub", ellipsize=True))
            c = t
        row.append(c)
    b.set_child(row)
    b.connect("clicked", lambda *_: cb())
    return b


def note(cls):
    """A wrapping line of text that never makes the menu wider, and hides itself while empty."""
    lb = label("", cls, wrap=True)
    lb.set_max_width_chars(34)
    lb.set_visible(False)
    return lb


def say(lb, text):
    lb.set_text(text)
    lb.set_visible(bool(text))
    refit(lb)


def refit(widget):
    """Ask the panel the widget is in to fit its content again."""
    root = widget.get_root()
    panel = getattr(root, "panel", None) if root else None
    if panel:
        panel.fit()


def heading(text):
    return label(text, "menu-head")


def sep():
    s = Gtk.Box()
    s.add_css_class("menu-sep")
    return s


def signal_icon(sig):
    for limit, name in ((75, "excellent"), (50, "good"), (25, "ok"), (0, "weak")):
        if sig >= limit:
            return f"network-wireless-signal-{name}-symbolic"
    return "network-wireless-signal-none-symbolic"


def open_settings(panel, page):
    spawn(["glass-launch", "glass-settings", "--page", page])
    panel.close()


class View(Gtk.Box):
    """One page of the panel. `back` is set when it was opened from the Control Centre."""

    def __init__(self, panel, back=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.panel = panel
        self.back = back

    def title_row(self, title, widget=None):
        r = hbox(8, "menu-pad")
        if self.back:
            b = ui.icon_button("go-previous-symbolic", lambda: self.panel.show("control"), "Back", "dot-btn")
            r.append(b)
        t = label(title, "menu-title")
        t.set_hexpand(True)
        t.set_valign(Gtk.Align.CENTER)
        r.append(t)
        if widget:
            widget.set_valign(Gtk.Align.CENTER)
            r.append(widget)
        return r

    def refresh(self):
        pass


# --------------------------------------------------------------------------- Wi-Fi
class WifiView(View):
    def __init__(self, panel, back=False):
        super().__init__(panel, back)
        self.sw = Gtk.Switch()
        self.sw.connect("state-set", self.on_switch)
        self.append(self.title_row("Wi-Fi", self.sw))
        self.note = note("sub menu-pad")
        self.append(self.note)
        self.lists = vbox(0)
        self.append(self.lists)
        self.msg = note("sub warn menu-pad")
        self.append(self.msg)
        self.append(sep())
        self.append(item(lambda: open_settings(panel, "network"), "Wi-Fi Settings…"))
        self.state = None
        self.joining = None      # the network being joined, shown as "Joining…"
        self.asking = None       # the network whose password box is open
        self.scanned = False

    def refresh(self, rescan=False):
        bg(lambda: hw.wifi_state(rescan), self.show)

    def on_switch(self, _sw, on):
        say(self.msg, "")
        bg(lambda: hw.run(["nmcli", "radio", "wifi", "on" if on else "off"]),
           lambda _r: GLib.timeout_add(1200, lambda: (self.refresh(rescan=on), False)[1]))
        return False

    def show(self, st):
        if isinstance(st, Exception):
            say(self.msg, str(st))
            return
        self.state = st
        self.sw.handler_block_by_func(self.on_switch)
        self.sw.set_active(st["radio"])
        self.sw.set_state(st["radio"])
        self.sw.handler_unblock_by_func(self.on_switch)
        self.sw.set_sensitive(st["adapter"])
        notes = []
        if not st["adapter"]:
            notes.append("No Wi-Fi adapter found.")
        if st["wired"]:
            notes.append(f"Connected by cable ({st['wired']}).")
        say(self.note, " ".join(notes))
        if self.asking:
            return  # don't wipe a password someone is typing
        ui.clear(self.lists)
        self.panel.fit()
        if not (st["adapter"] and st["radio"]):
            return
        nets = st["nets"]
        cur = [n for n in nets if n["inuse"]]
        known = [n for n in nets if not n["inuse"] and n["ssid"] in st["known"]]
        other = [n for n in nets if not n["inuse"] and n["ssid"] not in st["known"]]
        for title, group in (("Known Network", cur), ("Known Networks", known), ("Other Networks", other)):
            if not group:
                continue
            self.lists.append(heading(title))
            for n in group:
                self.lists.append(self.net_row(n))
        if not nets:
            self.lists.append(label("Looking for networks…" if not self.scanned else "No networks found.",
                                    "sub menu-pad"))
        if not self.scanned:
            # what's shown first is NetworkManager's last scan; look again, once, for fresh results
            self.scanned = True
            self.refresh(rescan=True)

    def net_row(self, n):
        ssid = n["ssid"]
        sub = "Joining…" if ssid == self.joining else None
        right = hbox(6)
        if n["secure"]:
            right.append(icon("system-lock-screen-symbolic", 13))
        right.append(icon(signal_icon(n["signal"]), 16))
        right.set_valign(Gtk.Align.CENTER)
        row = item(lambda: self.join(n), dot("network-wireless-symbolic", n["inuse"]), ssid, right, sub=sub)
        if n["inuse"]:
            row.set_tooltip_text("Connected")
        return row

    def join(self, n):
        ssid = n["ssid"]
        if n["inuse"] or self.joining:
            return
        say(self.msg, "")
        if ssid in self.state["known"]:
            self.start_join(ssid, lambda: hw.run(["nmcli", "connection", "up", "id", ssid], 60), new=False)
        elif not n["secure"]:
            self.start_join(ssid, lambda: hw.nm_connect_new(ssid), new=True)
        else:
            self.ask_password(ssid)

    def ask_password(self, ssid):
        self.asking = ssid
        ui.clear(self.lists)
        self.panel.fit()
        box = vbox(8, "menu-pad")
        box.append(label(f"Password for “{ssid}”", "menu-title"))
        pw = Gtk.PasswordEntry(show_peek_icon=True)
        box.append(pw)
        row = hbox(8)
        row.append(ui.spacer())

        def cancel():
            self.asking = None
            self.show(self.state)

        def go(*_):
            p = pw.get_text()
            if not p:
                return
            self.asking = None
            self.start_join(ssid, lambda: hw.nm_connect_new(ssid, p), new=True)

        row.append(ui.button("Cancel", cancel))
        row.append(ui.button("Join", go, "pill accent"))
        pw.connect("activate", go)
        box.append(row)
        self.lists.append(box)
        pw.grab_focus()

    def start_join(self, ssid, fn, new):
        self.joining = ssid
        self.show(self.state)

        def work():
            res = fn()
            if isinstance(res, tuple):          # nmcli connection up: waits for the result itself
                return res[0] == 0, (res[2] or res[1]).strip()
            # a new network: NetworkManager starts joining; wait to see if it gets there
            t0 = time.time()
            password_ok = False  # it got as far as asking the network for an address
            while time.time() - t0 < 40:
                st = hw.active_state(ssid)
                if st == "activated":
                    return True, ""
                if st is None and time.time() - t0 > 4:
                    break
                password_ok |= "IP configuration" in hw.wifi_device_state()
                time.sleep(0.5)
            if password_ok:
                return False, "address"
            if new:  # forget the half-made network, so trying again asks for the password again
                hw.run(["nmcli", "connection", "delete", "id", ssid], 10)
            return False, "password" if new else ""

        def done(res):
            self.joining = None
            if isinstance(res, Exception):
                why = getattr(res, "message", str(res))
                if "GDBus.Error" in why:  # "GDBus.Error:org.freedesktop...: Not authorized..." -> the words
                    why = why.split(": ", 1)[-1].split(" (", 1)[0]
                say(self.msg, f"Couldn't join “{ssid}”: {why}")
            elif not res[0]:
                say(self.msg, {
                    "address": f"Joined “{ssid}”, but it didn't give this computer an address. "
                               "Try again, or restart the router.",
                    "password": f"Couldn't join “{ssid}”. Check the password and try again.",
                }.get(res[1], f"Couldn't join “{ssid}”."))
            self.refresh()

        bg(work, done)


# --------------------------------------------------------------------------- Bluetooth
class BluetoothView(View):
    def __init__(self, panel, back=False):
        super().__init__(panel, back)
        self.sw = Gtk.Switch()
        self.sw.connect("state-set", self.on_switch)
        self.append(self.title_row("Bluetooth", self.sw))
        self.lists = vbox(0)
        self.append(self.lists)
        self.append(sep())
        self.append(item(lambda: open_settings(panel, "bluetooth"), "Bluetooth Settings…"))
        self.busy = None

    def refresh(self):
        bg(hw.bt_state, self.show)

    def on_switch(self, _sw, on):
        bg(lambda: hw.run(["bluetoothctl", "power", "on" if on else "off"], 10),
           lambda _r: GLib.timeout_add(600, lambda: (self.refresh(), False)[1]))
        return False

    def show(self, st):
        ui.clear(self.lists)
        self.panel.fit()
        if st is None or isinstance(st, Exception):
            self.sw.set_sensitive(False)
            self.lists.append(label("No Bluetooth adapter found.", "sub menu-pad"))
            return
        self.sw.handler_block_by_func(self.on_switch)
        self.sw.set_active(st["powered"])
        self.sw.set_state(st["powered"])
        self.sw.handler_unblock_by_func(self.on_switch)
        if not st["powered"]:
            return
        self.lists.append(heading("Devices"))
        if not st["devices"]:
            self.lists.append(label("No devices yet. Pair one in Bluetooth Settings.", "sub menu-pad", wrap=True))
        for d in st["devices"]:
            sub = "Connecting…" if d["mac"] == self.busy else ("Connected" if d["connected"] else None)
            self.lists.append(item(lambda d=d: self.toggle(d), dot("bluetooth-symbolic", d["connected"]),
                                   d["name"], sub=sub))

    def toggle(self, d):
        if self.busy:
            return
        self.busy = d["mac"]
        self.refresh()
        verb = "disconnect" if d["connected"] else "connect"

        def done(_r):
            self.busy = None
            self.refresh()

        bg(lambda: hw.run(["bluetoothctl", verb, d["mac"]], 25), done)


# --------------------------------------------------------------------------- Sound
def pill_slider(icon_name, lo, hi):
    """The Control Centre's fat slider, with its symbol riding in the knob's end.
    Returns (widget to add, the Gtk.Scale, the symbol)."""
    ov = Gtk.Overlay()
    sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
    sc.set_draw_value(False)
    sc.set_hexpand(True)
    sc.add_css_class("pill")
    ov.set_child(sc)
    im = icon(icon_name, 14)
    im.add_css_class("pill-icon")
    im.set_halign(Gtk.Align.START)
    im.set_valign(Gtk.Align.CENTER)
    im.set_margin_start(5)
    im.set_can_target(False)   # clicks go to the slider underneath
    ov.add_overlay(im)
    return ov, sc, im


def volume_row(panel_view, pill=False):
    """speaker button (mute) + slider for the default output; or, as a pill, just the slider
    with the speaker symbol inside it."""
    if pill:
        row, sc, sym = pill_slider("audio-volume-high-symbolic", 0, 100)
        mute = None
    else:
        row = hbox(8, "menu-pad")
        mute = Gtk.Button()
        mute.add_css_class("dot-btn")
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        sc.set_draw_value(False)
        sc.set_hexpand(True)
        row.append(mute)
        row.append(sc)
    state = {"muted": False, "quiet": False}

    def paint():
        v = sc.get_value()
        name = "muted" if state["muted"] or v == 0 else ("low" if v < 34 else "medium" if v < 67 else "high")
        if mute is None:
            sym.set_from_icon_name(f"audio-volume-{name}-symbolic")
            return
        mute.set_icon_name(f"audio-volume-{name}-symbolic")
        mute.set_tooltip_text("Unmute" if state["muted"] else "Mute")

    def changed(_s):
        if state["quiet"]:
            return
        if state["muted"]:
            state["muted"] = False
            spawn(["wpctl", "set-mute", SINK, "0"])
        spawn(["wpctl", "set-volume", "-l", "1.0", SINK, f"{sc.get_value() / 100:.2f}"])
        paint()

    def toggle_mute(*_):
        state["muted"] = not state["muted"]
        spawn(["wpctl", "set-mute", SINK, "1" if state["muted"] else "0"])
        paint()

    def load(res):
        if isinstance(res, Exception):
            return
        vol, muted = res
        state.update(quiet=True, muted=muted)
        sc.set_value(round(vol * 100))
        state["quiet"] = False
        paint()

    sc.connect("value-changed", changed)
    if mute is not None:
        mute.connect("clicked", toggle_mute)
    paint()
    return row, lambda: bg(lambda: hw.get_volume(SINK), load)


class SoundView(View):
    def __init__(self, panel, back=False):
        super().__init__(panel, back)
        self.append(self.title_row("Sound"))
        row, self.load_volume = volume_row(self)
        self.append(row)
        self.append(heading("Output"))
        self.outs = vbox(0)
        self.append(self.outs)
        self.append(sep())
        self.append(item(lambda: open_settings(panel, "sound"), "Sound Settings…"))

    def refresh(self):
        self.load_volume()
        bg(hw.wpctl_devices, self.show)

    def show(self, devs):
        ui.clear(self.outs)
        self.panel.fit()
        sinks = [] if isinstance(devs, Exception) else devs["sinks"]
        if not sinks:
            self.outs.append(label("No speakers or headphones found.", "sub menu-pad"))
        for sid, name, default in sinks:
            self.outs.append(item(lambda sid=sid: self.pick(sid), dot("audio-speakers-symbolic", default), name))

    def pick(self, sid):
        bg(lambda: hw.run(["wpctl", "set-default", sid]), lambda _r: self.refresh())


# --------------------------------------------------------------------------- Control Centre
DND = "do-not-disturb"   # the mako mode that hides notifications (see ~/.config/mako/config)


def media_state():
    """(status, title, artist) of the player playerctl picks, or None when nothing is playing."""
    rc, out, _ = hw.run(["playerctl", "metadata", "--format", "{{status}}\t{{title}}\t{{artist}}"], 3)
    if rc != 0 or not out.strip():
        return None
    parts = (out.strip().split("\t") + ["", "", ""])[:3]
    return tuple(parts)


def dnd_on():
    rc, out, _ = hw.run(["makoctl", "mode"], 3)
    return rc == 0 and DND in out.split()


class ControlView(View):
    """Laid out like macOS's Control Centre: the connections module and Focus side by side, two
    small shortcut tiles, then Display and Sound sliders and Now Playing across the full width."""

    def __init__(self, panel, back=False):
        super().__init__(panel, back)
        self.set_spacing(10)
        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)

        net = vbox(2, "cc-tile")
        self.wifi_btn, self.wifi_sub, r = self.toggle_row("network-wireless-symbolic", "Wi-Fi", self.toggle_wifi,
                                                          lambda: panel.show("wifi", back=True))
        net.append(r)
        self.bt_btn, self.bt_sub, r = self.toggle_row("bluetooth-symbolic", "Bluetooth", self.toggle_bt,
                                                      lambda: panel.show("bluetooth", back=True))
        net.append(r)
        grid.attach(net, 0, 0, 1, 2)

        focus = vbox(0, "cc-tile")
        self.dnd_btn, self.dnd_sub, r = self.toggle_row("notifications-disabled-symbolic", "Focus",
                                                        self.toggle_dnd, self.toggle_dnd)
        focus.append(r)
        grid.attach(focus, 1, 0, 1, 1)

        smalls = Gtk.Box(spacing=10, homogeneous=True)
        smalls.append(self.small_tile("applets-screenshooter-symbolic", "Capture", self.screenshot))
        smalls.append(self.small_tile("preferences-system-symbolic", "Settings",
                                      lambda: open_settings(panel, "appearance")))
        grid.attach(smalls, 1, 1, 1, 1)
        self.append(grid)

        disp = vbox(4, "cc-tile")
        disp.append(self.tile_head("Display", lambda: open_settings(panel, "displays")))
        self.bright_row, self.bright, _ = pill_slider("display-brightness-symbolic", 1, 100)
        self.bright.connect("value-changed", self.on_bright)
        disp.append(self.bright_row)
        self.bright_note = label("This screen's brightness is set with its own buttons.", "cc-sub", wrap=True)
        self.bright_note.set_margin_start(4)
        self.bright_note.set_visible(False)   # until we know there's no way to set it
        disp.append(self.bright_note)
        self.append(disp)

        snd = vbox(4, "cc-tile")
        snd.append(self.tile_head("Sound", lambda: panel.show("sound", back=True)))
        row, self.load_volume = volume_row(self, pill=True)
        snd.append(row)
        self.append(snd)

        self.append(self.now_playing())
        self.quiet = False
        self.wifi_on = self.bt_on = self.dnd = False

    # ---- building blocks
    def toggle_row(self, icon_name, title, on_toggle, on_open):
        """round toggle button + name and state; clicking the words opens the details."""
        r = hbox(2)
        r.set_vexpand(True)
        btn = Gtk.Button.new_from_icon_name(icon_name)
        btn.add_css_class("cc-round")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", lambda *_: on_toggle())
        r.append(btn)
        sub = label("", "cc-sub", ellipsize=True)
        t = vbox(0)
        t.set_valign(Gtk.Align.CENTER)
        t.append(label(title, "cc-name", ellipsize=True))
        t.append(sub)
        opener = Gtk.Button()
        opener.add_css_class("cc-cell")
        opener.set_hexpand(True)
        opener.set_child(t)
        opener.connect("clicked", lambda *_: on_open())
        r.append(opener)
        return btn, sub, r

    def small_tile(self, icon_name, title, cb):
        tile = vbox(0, "cc-tile")
        tile.set_hexpand(True)
        b = Gtk.Button()
        b.add_css_class("cc-cell")
        b.set_vexpand(True)
        inner = vbox(4)
        inner.set_valign(Gtk.Align.CENTER)
        d = dot(icon_name)
        d.set_halign(Gtk.Align.CENTER)
        inner.append(d)
        inner.append(label(title, "cc-small-name", xalign=0.5, ellipsize=True))
        b.set_child(inner)
        b.connect("clicked", lambda *_: cb())
        tile.append(b)
        return tile

    def tile_head(self, title, cb):
        b = Gtk.Button()
        b.add_css_class("cc-cell")
        b.set_halign(Gtk.Align.START)
        b.set_child(label(title, "cc-name"))
        b.connect("clicked", lambda *_: cb())
        return b

    def now_playing(self):
        tile = hbox(10, "cc-tile")
        art = icon("audio-x-generic-symbolic", 20)   # stands in for the album cover
        art.add_css_class("cc-art")
        art.set_valign(Gtk.Align.CENTER)
        tile.append(art)
        words = vbox(0)
        words.set_hexpand(True)
        words.set_valign(Gtk.Align.CENTER)
        self.np_title = label("Not Playing", "cc-name", ellipsize=True)
        self.np_artist = label("", "cc-sub", ellipsize=True)
        self.np_artist.set_visible(False)
        words.append(self.np_title)
        words.append(self.np_artist)
        tile.append(words)
        self.np_play = ui.icon_button("media-playback-start-symbolic", lambda: self.media("play-pause"),
                                      "Play", "cc-media")
        self.np_next = ui.icon_button("media-skip-forward-symbolic", lambda: self.media("next"),
                                      "Next", "cc-media")
        for b in (self.np_play, self.np_next):
            b.set_valign(Gtk.Align.CENTER)
            tile.append(b)
        return tile

    # ---- state
    def refresh(self):
        def work():
            w = hw.wifi_state()
            return w, hw.bt_state(), hw.brightness(), hw.has_backlight(), dnd_on(), media_state()

        bg(work, self.show)
        self.load_volume()

    def show(self, res):
        if isinstance(res, Exception):
            return
        w, bt, br, backlight, dnd, media = res
        self.wifi_on = w["radio"] and w["adapter"]
        cur = next((n["ssid"] for n in w["nets"] if n["inuse"]), None)
        if not w["adapter"]:
            self.wifi_sub.set_text("No adapter")
        else:
            self.wifi_sub.set_text(cur or ("Not connected" if self.wifi_on else "Off"))
        self.wifi_btn.set_sensitive(w["adapter"])
        (self.wifi_btn.add_css_class if self.wifi_on else self.wifi_btn.remove_css_class)("on")
        self.bt_on = bool(bt and bt["powered"])
        if bt is None:
            self.bt_sub.set_text("No adapter")
        else:
            names = [d["name"] for d in bt["devices"] if d["connected"]]
            self.bt_sub.set_text(", ".join(names) if names else ("On" if self.bt_on else "Off"))
        self.bt_btn.set_sensitive(bt is not None)
        (self.bt_btn.add_css_class if self.bt_on else self.bt_btn.remove_css_class)("on")
        self.show_dnd(dnd)
        self.show_media(media)
        self.panel.fit()
        self.bright_row.set_visible(br is not None)
        self.bright_note.set_visible(br is None)
        if br is not None:
            # quiet first: set_range clamps the slider's value and fires value-changed, which
            # would otherwise apply the range's minimum (dimming the screen when the panel opens)
            self.quiet = True
            self.bright.set_range(1 if backlight else hw.SOFT_MIN, 100)
            self.bright.set_value(max(1, br))
            self.quiet = False

    def show_dnd(self, on):
        self.dnd = on
        self.dnd_sub.set_text("Do Not Disturb" if on else "Off")
        (self.dnd_btn.add_css_class if on else self.dnd_btn.remove_css_class)("on")
        self.dnd_btn.set_tooltip_text("Show notifications again" if on else "Hide notifications")

    def show_media(self, m):
        playing = m is not None
        status, title, artist = m or ("", "", "")
        self.np_title.set_text(title or ("Playing" if playing else "Not Playing"))
        self.np_artist.set_text(artist)
        self.np_artist.set_visible(bool(artist))
        self.np_play.set_icon_name("media-playback-pause-symbolic" if status == "Playing"
                                   else "media-playback-start-symbolic")
        self.np_play.set_tooltip_text("Pause" if status == "Playing" else "Play")
        for b in (self.np_play, self.np_next):
            b.set_sensitive(playing)

    # ---- actions
    def toggle_wifi(self):
        on = not self.wifi_on
        bg(lambda: hw.run(["nmcli", "radio", "wifi", "on" if on else "off"]),
           lambda _r: GLib.timeout_add(800, lambda: (self.refresh(), False)[1]))

    def toggle_bt(self):
        on = not self.bt_on
        bg(lambda: hw.run(["bluetoothctl", "power", "on" if on else "off"], 10),
           lambda _r: GLib.timeout_add(500, lambda: (self.refresh(), False)[1]))

    def toggle_dnd(self):
        self.show_dnd(not self.dnd)   # answer the click at once; the real state follows
        bg(lambda: (hw.run(["makoctl", "mode", "-t", DND], 3), dnd_on())[1], self.show_dnd)

    def media(self, verb):
        bg(lambda: (hw.run(["playerctl", verb], 3), time.sleep(0.3), media_state())[2], self.show_media)

    def screenshot(self):
        self.panel.close()
        # wait for the panel to leave the screen, then let the person drag out an area
        spawn(["sh", "-c", "sleep 0.4; exec glass-screenshot area"])

    def on_bright(self, s):
        if not self.quiet:
            set_brightness_soon(int(s.get_value()))


_bright = {"want": None, "busy": False}


def set_brightness_soon(pct):
    """Set the brightness off the UI thread; while the slider is dragged only the latest value is
    applied, so the screen keeps up without a queue of stale levels."""
    _bright["want"] = pct
    if _bright["busy"]:
        return

    def work():
        while _bright["want"] is not None:
            v, _bright["want"] = _bright["want"], None
            hw.set_brightness(v)
        _bright["busy"] = False

    _bright["busy"] = True
    threading.Thread(target=work, daemon=True).start()


# --------------------------------------------------------------------------- Window
def glass_window(action, address):
    spawn(["hyprctl", "eval", f'glass_window("{action}", "{address}")'])


class WindowView(View):
    """The top bar's app name: Close, Minimize, Full Size and Center for the focused window, so
    every window can be closed and found again, even one that has no title bar."""

    def __init__(self, panel, back=False):
        super().__init__(panel, back)
        try:
            w = json.loads(ui.hypr("j/activewindow") or "{}") or {}
        except ValueError:
            w = {}
        addr = w.get("address", "")
        if addr.startswith("0x"):
            addr = addr[2:]
        name = w.get("title") or w.get("class") or ""
        if not addr:
            self.append(self.title_row("No window"))
            self.append(label("Open an app, then click its name here to close, minimize or move it.",
                              "sub menu-pad", wrap=True))
            return
        if len(name) > 38:
            name = name[:37] + "…"
        self.append(self.title_row(name or "Window"))
        self.append(sep())
        full = w.get("fullscreen", 0) not in (0, False)

        def act(action):
            glass_window(action, "0x" + addr)
            panel.close()

        for text, icon_name, action in (
            ("Close Window", "window-close-symbolic", "close"),
            ("Minimize", "window-minimize-symbolic", "minimize"),
            ("Exit Full Size" if full else "Full Size", "view-fullscreen-symbolic", "full"),
            ("Center on Screen", "zoom-fit-best-symbolic", "center"),
        ):
            self.append(item(lambda a=action: act(a), icon(icon_name), text))


VIEWS = {"wifi": WifiView, "bluetooth": BluetoothView, "sound": SoundView, "control": ControlView,
         "window": WindowView}


# --------------------------------------------------------------------------- the window
def pointer_place(width=WIDTH):
    """(gdk monitor or None, left margin) to open the panel centred under the mouse pointer,
    kept on its screen."""
    try:
        cur = json.loads(ui.hypr("j/cursorpos"))
        mons = json.loads(ui.hypr("j/monitors"))
    except ValueError:
        return None, None
    for m in mons:
        s = m.get("scale") or 1
        w, h = m["width"] / s, m["height"] / s
        if m.get("transform", 0) % 2:
            w, h = h, w
        if m["x"] <= cur["x"] < m["x"] + w and m["y"] <= cur["y"] < m["y"] + h:
            left = int(min(max(cur["x"] - m["x"] - width / 2, 8), w - width - 8))
            gm = None
            ms = Gdk.Display.get_default().get_monitors()
            for i in range(ms.get_n_items()):
                if ms.get_item(i).get_connector() == m.get("name"):
                    gm = ms.get_item(i)
            return gm, left
    return None, None


def layer(win, namespace, level, monitor):
    Layer.init_for_window(win)
    Layer.set_namespace(win, namespace)
    Layer.set_layer(win, level)
    if monitor is not None:
        Layer.set_monitor(win, monitor)


class Panel:
    def __init__(self, app, view):
        self.app = app
        monitor, left = pointer_place(CC_WIDTH if view == "control" else WIDTH)
        top = 0
        for area in ui.work_areas():
            top = max(top, int(area[1] - area[4]))  # the top bar's height plus its gap

        # an invisible sheet over the whole screen: a click anywhere outside the menu closes it.
        # Its name mustn't match a blur rule: Hyprland lets clicks through see-through parts of
        # layers that have ignore_alpha set, and this sheet is all see-through.
        self.catcher = Gtk.Window(application=app)
        self.catcher.remove_css_class("background")  # GlassOS's gtk.css tints every window.background
        self.catcher.add_css_class("catcher")
        layer(self.catcher, "glass-clickaway", Layer.Layer.TOP, monitor)
        for e in (Layer.Edge.TOP, Layer.Edge.BOTTOM, Layer.Edge.LEFT, Layer.Edge.RIGHT):
            Layer.set_anchor(self.catcher, e, True)
        Layer.set_exclusive_zone(self.catcher, -1)
        Layer.set_keyboard_mode(self.catcher, Layer.KeyboardMode.NONE)
        click = Gtk.GestureClick(button=0)
        click.connect("pressed", lambda *_: self.close())
        self.catcher.add_controller(click)
        self.catcher.set_child(Gtk.Box())

        self.win = Gtk.Window(application=app)
        self.win.panel = self
        self.win.remove_css_class("background")
        self.win.add_css_class("panel-win")
        layer(self.win, "glass-panel", Layer.Layer.OVERLAY, monitor)
        Layer.set_anchor(self.win, Layer.Edge.TOP, True)
        Layer.set_margin(self.win, Layer.Edge.TOP, max(top, 40))
        if left is None:
            Layer.set_anchor(self.win, Layer.Edge.RIGHT, True)
            Layer.set_margin(self.win, Layer.Edge.RIGHT, 10)
        else:
            Layer.set_anchor(self.win, Layer.Edge.LEFT, True)
            Layer.set_margin(self.win, Layer.Edge.LEFT, left)
        Layer.set_keyboard_mode(self.win, Layer.KeyboardMode.ON_DEMAND)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, _k, _m: kv == Gdk.KEY_Escape and (self.close() or True))
        self.win.add_controller(keys)
        self.menu = vbox(0, "menu")
        self.win.set_child(self.menu)
        self.view = None
        self._fit = 0
        self.show(view)
        self.catcher.present()
        self.win.present()

    def show(self, name, back=False):
        if self.view is not None:
            self.menu.remove(self.view)
        self.view = VIEWS[name](self, back)
        cc = name == "control"
        (self.menu.add_css_class if cc else self.menu.remove_css_class)("cc")
        self.menu.set_size_request(CC_WIDTH if cc else WIDTH, -1)
        self.menu.append(self.view)
        self.view.refresh()
        self.fit()

    def fit(self):
        """Shrink the panel to its content again (a window keeps its size when content goes away)."""
        if not self._fit:
            self._fit = GLib.idle_add(self._do_fit)

    def _do_fit(self):
        self._fit = 0
        self.win.set_default_size(1, 1)
        return False

    def close(self):
        self.win.close()
        self.catcher.close()
        self.app.quit()


class PanelApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.panel = None

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        view = args[0] if args and args[0] in VIEWS else "control"
        if self.panel is not None:      # asked again while open: close it, like clicking the icon again
            self.panel.close()
            return 0
        ui.apply_css(css())
        self.panel = Panel(self, view)
        return 0


if __name__ == "__main__":
    if os.environ.get("WAYLAND_DISPLAY") is None:
        print(__doc__.strip())
        sys.exit(1)
    sys.exit(PanelApp().run(sys.argv))
