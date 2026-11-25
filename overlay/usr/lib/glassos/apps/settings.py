#!/usr/bin/python3
"""Glass Settings - the GlassOS settings app.

Everything it changes is a plain file you can read:
  ~/.config/glassos/settings.json     what you picked (input, displays, frost, idle timers)
  ~/.config/hypr/glass-settings.lua   the same, written out for the desktop (Hyprland)
  ~/.config/glassos/appearance.json   glass level, accent and dock size for GlassOS apps
  ~/.config/hypr/hypridle.conf        dim / lock / screen-off timers
  ~/.config/hypr/glass-keys.lua       keyboard shortcuts (the styles are in /usr/lib/glassos/glasskeys.py)
System-wide things (Wi-Fi, Bluetooth, time zone) go through NetworkManager, BlueZ and systemd.

Usage: glass-settings [--page network|bluetooth|displays|sound|appearance|input|shortcuts|time|power|privacy|users|updates|about]
"""
import glob
import json
import os
import pwd
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, "/usr/lib/glassos")
sys.path.insert(0, "/usr/lib/glassos/lens")
import glassui as ui  # noqa: E402
import glasshw  # noqa: E402
import glasskeys  # noqa: E402
from glasshw import get_volume, nm_connect_new, nm_split, wpctl_devices  # noqa: E402
from glassui import hbox, label, vbox  # noqa: E402
import gi  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

APP_ID = "os.glass.Settings"
HOME = os.path.expanduser("~")
CFG = os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))
STATE = os.path.join(CFG, "glassos", "settings.json")
LUA = os.path.join(CFG, "hypr", "glass-settings.lua")
IDLE = os.path.join(CFG, "hypr", "hypridle.conf")
WAYBAR = os.path.join(CFG, "waybar", "top.jsonc")

CSS = """
.wall-thumb { border-radius: 12px; border: 2px solid transparent; }
.wall-thumb.current { border-color: alpha(#ffffff, 0.9); }
flowboxchild { padding: 0; background: none; }
.swatch { min-width: 26px; min-height: 26px; border-radius: 99px; padding: 0; border: 2px solid alpha(#ffffff, 0.25); }
.swatch.current { border-color: #ffffff; }
.icon-style { background: none; border: 2px solid transparent; border-radius: 18px; padding: 8px 10px 6px 10px; }
.icon-style:hover { background: alpha(#ffffff, 0.06); }
.icon-style.current { border-color: alpha(#ffffff, 0.85); background: alpha(#ffffff, 0.08); }
.bars { font-family: "JetBrains Mono", monospace; letter-spacing: -1px; }
.kbd { font-family: "JetBrains Mono", monospace; font-size: 12px; padding: 3px 9px; border-radius: 8px;
       background: alpha(#ffffff, 0.10); border: 1px solid alpha(#ffffff, 0.18); }
.big-kbd { font-size: 20px; padding: 14px; }
button.style-pick.current { background-image: none; background: alpha(#ffffff, 0.85); color: #10111a; }
.clock-big { font-size: 34px; font-weight: 700; font-feature-settings: "tnum"; }
"""


# --------------------------------------------------------------------------- helpers
def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:  # missing tool, timeout...
        return 1, "", str(e)


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


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def lua_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {lua_value(x)}" for k, x in v.items()) + " }"
    if isinstance(v, list):
        return "{ " + ", ".join(lua_value(x) for x in v) + " }"
    return json.dumps(str(v), ensure_ascii=False)


def save_state(changes, reload_monitors=False):
    st = load_state()
    st.update(changes)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE + ".tmp", "w") as f:
        json.dump(st, f, indent=2)
    os.replace(STATE + ".tmp", STATE)
    keys = ["frost_size", "frost_passes", "frost_vibrancy", "frost_brightness", "frost_noise", "kb_layout", "kb_variant", "sensitivity",
            "mouse_natural_scroll", "touchpad_natural_scroll", "tap_to_click"]
    lines = ["-- Written by GlassOS Settings. It's rewritten whenever you change a setting,",
             "-- so put your own changes in custom.lua instead.", "return {"]
    for k in keys:
        if k in st:
            lines.append(f"    {k} = {lua_value(st[k])},")
    mons = [dict(output=n, **m) for n, m in st.get("monitors", {}).items()]
    if mons:
        lines.append("    monitors = {")
        for m in mons:
            lines.append(f"        {lua_value(m)},")
        lines.append("    },")
    lines.append("}")
    os.makedirs(os.path.dirname(LUA), exist_ok=True)
    with open(LUA + ".tmp", "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(LUA + ".tmp", LUA)
    spawn(["hyprctl", "reload"] if reload_monitors else ["hyprctl", "reload", "config-only"])
    return st


def desktop_conf():
    out = {}
    try:
        for line in open(os.path.join(CFG, "glassos", "desktop.conf")):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def set_desktop_conf(key, value):
    p = os.path.join(CFG, "glassos", "desktop.conf")
    try:
        lines = [ln for ln in open(p).read().splitlines() if ln.split("=", 1)[0].strip() != key]
    except OSError:
        lines = []
    lines.append(f"{key}={value}")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(p + ".tmp", p)


class Page(Gtk.ScrolledWindow):
    title = ""
    icon = ""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.body = vbox(14, "page")
        self.set_child(self.body)

    def header(self, title, sub=None):
        self.body.append(label(title, "page-title"))
        if sub:
            self.body.append(label(sub, "page-sub", wrap=True))

    def refresh(self):
        pass


def set_icon_theme(theme):
    """Use an icon theme everywhere: GTK 3 and 4 apps, the launcher and notifications."""
    def set_key(path, key, value, section=None):
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            text = f"[{section}]\n" if section else ""
        if re.search(rf"^{re.escape(key)}=.*$", text, re.M):
            text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{key}={value}\n"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    for v in ("gtk-3.0", "gtk-4.0"):
        set_key(os.path.join(CFG, v, "settings.ini"), "gtk-icon-theme-name", theme, "Settings")
    set_key(os.path.join(CFG, "fuzzel", "fuzzel.ini"), "icon-theme", theme, "main")
    mako = os.path.join(CFG, "mako", "config")
    if os.path.exists(mako):
        set_key(mako, "icon-path", f"/usr/share/icons/{theme}:/usr/share/icons/Papirus-Dark")
        spawn(["makoctl", "reload"])
    # running apps follow this setting (the gsettings tool isn't installed, so set it directly)
    src = Gio.SettingsSchemaSource.get_default()
    if src and src.lookup("org.gnome.desktop.interface", True):
        s = Gio.Settings.new("org.gnome.desktop.interface")
        s.set_string("icon-theme", theme)
        Gio.Settings.sync()


def switch(active, cb):
    s = Gtk.Switch()
    s.set_active(active)
    s.connect("notify::active", lambda w, _p: cb(w.get_active()))
    return s


def dropdown(items, selected=0, cb=None, search=False):
    dd = Gtk.DropDown.new_from_strings(items)
    if 0 <= selected < len(items):
        dd.set_selected(selected)
    if search:
        dd.set_enable_search(True)
        dd.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
    if cb:
        dd.connect("notify::selected", lambda d, _p: cb(d.get_selected()))
    return dd


# --------------------------------------------------------------------------- Wi-Fi
class NetworkPage(Page):
    title, icon = "Wi-Fi & Network", "network-wireless-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Wi-Fi & Network", "Your Wi-Fi hardware address is randomized while scanning and is "
                    "different on each network. The connectivity check is off, so joining a network doesn't "
                    "contact a test server.")
        top = ui.card()
        self.wifi_switch = Gtk.Switch()
        self.wifi_switch.connect("notify::active", self.on_radio)
        top.append(ui.setting_row("Wi-Fi", None, self.wifi_switch))
        self.devs = vbox(0)
        top.append(self.devs)
        self.body.append(top)
        nets = ui.card("Networks nearby")
        row = hbox(8)
        self.scan_msg = label("", "dim small")
        self.scan_msg.set_hexpand(True)
        row.append(self.scan_msg)
        row.append(ui.button("Scan again", lambda: self.refresh(rescan=True)))
        nets.append(row)
        self.list = vbox(0)
        nets.append(self.list)
        self.body.append(nets)
        self.msg = label("", "small warn", wrap=True)
        self.body.append(self.msg)
        self._busy = False

    def on_radio(self, sw, _p):
        if self._busy:
            return
        run(["nmcli", "radio", "wifi", "on" if sw.get_active() else "off"])
        GLib.timeout_add(1500, lambda: (self.refresh(), False)[1])

    def refresh(self, rescan=False):
        def work():
            _, radio, _ = run(["nmcli", "-t", "-f", "WIFI", "radio"])
            _, devs, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
            _, known, _ = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
            _, nets, _ = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                              "--rescan", "yes" if rescan else "auto"], timeout=25)
            return radio.strip(), devs, known, nets

        self.scan_msg.set_text("Looking for networks…")
        bg(work, self.show)

    def show(self, res):
        if isinstance(res, Exception):
            self.msg.set_text(str(res))
            return
        radio, devs, known, nets = res
        self._busy = True
        self.wifi_switch.set_active(radio == "enabled")
        self._busy = False
        ui.clear(self.devs)
        has_wifi = False
        for line in devs.splitlines():
            p = nm_split(line)
            if len(p) < 4 or p[1] in ("loopback", "wifi-p2p", "bridge", "tun"):
                continue
            has_wifi |= p[1] == "wifi"
            kind = {"wifi": "Wi-Fi", "ethernet": "Wired"}.get(p[1], p[1])
            state = p[2].split(" ")[0]
            txt = f"{kind} ({p[0]})"
            st = f"{state}{' to ' + p[3] if p[3] and p[3] != '--' else ''}"
            r = hbox(10, "row")
            r.append(label(txt))
            r.append(ui.spacer())
            r.append(label(st, "dim small"))
            self.devs.append(r)
        self.known = {nm_split(l)[0] for l in known.splitlines() if l.endswith(":802-11-wireless")}
        ui.clear(self.list)
        if not has_wifi:
            self.scan_msg.set_text("No Wi-Fi adapter found.")
            return
        seen = set()
        count = 0
        for line in nets.splitlines():
            p = nm_split(line)
            if len(p) < 4 or not p[1] or p[1] in seen:
                continue
            seen.add(p[1])
            count += 1
            inuse, ssid, sig, sec = p[0] == "*", p[1], int(p[2] or 0), p[3]
            bars = "▂▄▆█"[: max(1, min(4, sig // 25 + 1))]
            r = hbox(10, "row")
            r.append(label(f"{bars:<4}", "bars dim"))
            n = vbox(1)
            n.set_hexpand(True)
            n.append(label(ssid))
            n.append(label(("Connected · " if inuse else "") + (sec if sec and sec != "--" else "Open (not encrypted)"),
                           "dim small"))
            r.append(n)
            if inuse:
                r.append(ui.button("Disconnect", lambda s=ssid: self.disconnect(s)))
            else:
                r.append(ui.button("Connect", lambda s=ssid, secure=(sec not in ("", "--")): self.connect(s, secure)))
            self.list.append(r)
        self.scan_msg.set_text(f"{count} network{'s' if count != 1 else ''} found")

    def disconnect(self, ssid):
        bg(lambda: run(["nmcli", "connection", "down", "id", ssid]), lambda _r: self.refresh())

    def connect(self, ssid, secure):
        if ssid in self.known:
            self.msg.set_text(f"Connecting to {ssid}…")
            bg(lambda: run(["nmcli", "connection", "up", "id", ssid], timeout=60), self.after_connect)
            return
        if not secure:
            self.do_connect(ssid, None)
            return
        dlg = Gtk.Window(transient_for=self.win, modal=True, title=f"Join {ssid}")
        dlg.add_css_class("glass")
        dlg.add_css_class("solid")
        dlg.set_default_size(380, -1)
        b = vbox(12)
        for m in ("top", "bottom", "start", "end"):
            getattr(b, f"set_margin_{m}")(20)
        b.append(label(f"Password for “{ssid}”", "card-title"))
        pw = Gtk.PasswordEntry(show_peek_icon=True)
        b.append(pw)
        row = hbox(8)
        row.append(ui.spacer())
        row.append(ui.button("Cancel", dlg.close))

        def go(*_):
            p = pw.get_text()
            dlg.close()
            self.do_connect(ssid, p)

        row.append(ui.button("Join", go, "pill accent"))
        pw.connect("activate", go)
        b.append(row)
        dlg.set_child(b)
        dlg.present()

    def do_connect(self, ssid, password):
        self.msg.set_text(f"Connecting to {ssid}…")
        bg(lambda: nm_connect_new(ssid, password), self.after_connect)

    def after_connect(self, res):
        if isinstance(res, Exception):
            self.msg.set_text(f"Couldn't connect: {getattr(res, 'message', str(res))}")
        elif isinstance(res, tuple) and res[0] != 0:
            self.msg.set_text("Couldn't connect: " + (res[2] or res[1]).strip())
        else:
            self.msg.set_text("")
        GLib.timeout_add(1500, lambda: (self.refresh(), False)[1])


# --------------------------------------------------------------------------- Bluetooth
class BluetoothPage(Page):
    title, icon = "Bluetooth", "bluetooth-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Bluetooth", "Bluetooth stays off until you turn it on, and this computer is only visible "
                    "to others while this page is scanning.")
        c = ui.card()
        self.sw = Gtk.Switch()
        self.sw.connect("notify::active", self.on_power)
        c.append(ui.setting_row("Bluetooth", None, self.sw))
        self.state = label("", "dim small")
        c.append(self.state)
        self.body.append(c)
        self.devs_card = ui.card("Devices")
        row = hbox(8)
        self.scan_msg = label("", "dim small")
        self.scan_msg.set_hexpand(True)
        row.append(self.scan_msg)
        self.scan_btn = ui.button("Look for devices", self.scan)
        row.append(self.scan_btn)
        self.devs_card.append(row)
        self.devs = vbox(0)
        self.devs_card.append(self.devs)
        self.body.append(self.devs_card)
        self._busy = False

    def on_power(self, sw, _p):
        if self._busy:
            return
        bg(lambda: run(["bluetoothctl", "power", "on" if sw.get_active() else "off"]), lambda _r: self.refresh())

    def refresh(self):
        def work():
            code, show, err = run(["bluetoothctl", "show"], 5)
            if code != 0 or "No default controller" in show + err:
                return None
            powered = "Powered: yes" in show
            devices = []
            _, out, _ = run(["bluetoothctl", "devices"], 5)
            for line in out.splitlines():
                m = re.match(r"Device ([0-9A-F:]{17}) (.*)", line)
                if not m:
                    continue
                _, info, _ = run(["bluetoothctl", "info", m.group(1)], 5)
                devices.append({"mac": m.group(1), "name": m.group(2), "paired": "Paired: yes" in info,
                                "connected": "Connected: yes" in info})
            return powered, devices

        bg(work, self.show)

    def show(self, res):
        if res is None or isinstance(res, Exception):
            self.sw.set_sensitive(False)
            self.state.set_text("No Bluetooth adapter found (or the Bluetooth service isn't running).")
            self.devs_card.set_visible(False)
            return
        powered, devices = res
        self._busy = True
        self.sw.set_active(powered)
        self._busy = False
        self.state.set_text("On" if powered else "Off")
        self.devs_card.set_visible(powered)
        ui.clear(self.devs)
        devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
        for d in devices:
            r = hbox(10, "row")
            n = vbox(1)
            n.set_hexpand(True)
            n.append(label(d["name"]))
            n.append(label("Connected" if d["connected"] else ("Paired" if d["paired"] else "Nearby"), "dim small"))
            r.append(n)
            mac = d["mac"]
            if d["connected"]:
                r.append(ui.button("Disconnect", lambda m=mac: self.act(["disconnect", m])))
            elif d["paired"]:
                r.append(ui.button("Connect", lambda m=mac: self.act(["connect", m])))
            else:
                r.append(ui.button("Pair", lambda m=mac: self.pair(m), "pill accent"))
            if d["paired"]:
                r.append(ui.button("Forget", lambda m=mac: self.act(["remove", m])))
            self.devs.append(r)

    def act(self, args):
        bg(lambda: run(["bluetoothctl"] + args, 20), lambda _r: self.refresh())

    def pair(self, mac):
        self.scan_msg.set_text("Pairing… (if the device shows a code, accept it there)")

        def work():
            for args in (["pair", mac], ["trust", mac], ["connect", mac]):
                code, out, err = run(["bluetoothctl", "--agent", "NoInputNoOutput"] + args, 30)
                if code != 0 and args[0] == "pair" and "AlreadyExists" not in out + err:
                    return (out + err).strip().splitlines()[-1:] or ["Pairing failed"]
            return None

        bg(work, lambda e: (self.scan_msg.set_text(f"Couldn't pair: {e[0]}" if e else ""), self.refresh()))

    def scan(self):
        self.scan_btn.set_sensitive(False)
        self.scan_msg.set_text("Looking for devices for 10 seconds…")

        def done(_r):
            self.scan_btn.set_sensitive(True)
            self.scan_msg.set_text("")
            self.refresh()

        bg(lambda: run(["bluetoothctl", "--timeout", "10", "scan", "on"], 20), done)


# --------------------------------------------------------------------------- Displays
class DisplaysPage(Page):
    title, icon = "Displays", "video-display-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Displays", "Resolution, refresh rate and scaling for each screen.")
        self.box = vbox(14)
        self.body.append(self.box)
        self.bright = ui.card("Brightness")
        self.bscale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1)
        self.bscale.set_draw_value(False)
        self.bquiet = False
        self.bwant = None
        self.bscale.connect("value-changed", self.on_bright)
        self.bright.append(self.bscale)
        self.body.append(self.bright)

    def refresh(self):
        ui.clear(self.box)
        code, out, _ = run(["hyprctl", "-j", "monitors"])
        try:
            mons = json.loads(out) if code == 0 else []
        except ValueError:
            mons = []
        if not mons:
            self.box.append(label("Couldn't read the screen list from the desktop.", "dim"))
        st = load_state().get("monitors", {})
        for m in mons:
            c = ui.card(m.get("description") or m["name"], f"{m['name']} · now {m['width']}×{m['height']} at "
                        f"{m['refreshRate']:.0f} Hz, scale {m['scale']:g}")
            modes = []
            for md in m.get("availableModes", []):
                mm = re.match(r"(\d+)x(\d+)@([\d.]+)Hz", md)
                if mm:
                    modes.append((int(mm.group(1)), int(mm.group(2)), float(mm.group(3))))
            modes = sorted(set(modes), key=lambda x: (-x[0] * x[1], -x[2]))
            labels = [f"{w} × {h}  ·  {r:.0f} Hz" for w, h, r in modes] or [f"{m['width']} × {m['height']}"]
            cur = 0
            for i, (w, h, r) in enumerate(modes):
                if w == m["width"] and h == m["height"] and abs(r - m["refreshRate"]) < 1:
                    cur = i
                    break
            mode_dd = dropdown(labels, cur)
            c.append(ui.setting_row("Resolution", None, mode_dd))
            scales = [1.0, 1.25, 1.5, 1.75, 2.0]
            sc_dd = dropdown([f"{int(s * 100)}%" for s in scales],
                             min(range(len(scales)), key=lambda i: abs(scales[i] - m["scale"])))
            c.append(ui.setting_row("Scale", "Makes text and windows bigger on sharp screens.", sc_dd))
            row = hbox(8)
            row.append(ui.spacer())
            if m["name"] in st:
                row.append(ui.button("Use automatic", lambda n=m["name"]: self.reset(n)))

            def apply(n=m["name"], md=mode_dd, sd=sc_dd, modes=modes):
                mode = "preferred"
                if modes:
                    w, h, r = modes[md.get_selected()]
                    mode = f"{w}x{h}@{r:.2f}"
                mons_state = load_state().get("monitors", {})
                mons_state[n] = {"mode": mode, "position": "auto", "scale": scales[sd.get_selected()]}
                save_state({"monitors": mons_state}, reload_monitors=True)
                GLib.timeout_add(1500, lambda: (self.refresh(), False)[1])

            row.append(ui.button("Apply", apply, "pill accent"))
            c.append(row)
            self.box.append(c)
        # always shown: a screen without a backlight (a VM, most external monitors) is dimmed in
        # software instead (glasshw.set_brightness)
        self.bright.set_visible(True)
        self.bscale.set_range(5 if glasshw.has_backlight() else glasshw.SOFT_MIN, 100)
        self.bquiet = True
        self.bscale.set_value(glasshw.brightness())
        self.bquiet = False

    def on_bright(self, s):
        """Applied off the UI thread; while dragging, only the latest level is set."""
        if self.bquiet:
            return
        busy = self.bwant is not None
        self.bwant = int(s.get_value())
        if busy:
            return

        def work():
            while True:
                v = self.bwant
                glasshw.set_brightness(v)
                if self.bwant == v:
                    self.bwant = None
                    return
        threading.Thread(target=work, daemon=True).start()

    def reset(self, name):
        mons_state = load_state().get("monitors", {})
        mons_state.pop(name, None)
        save_state({"monitors": mons_state}, reload_monitors=True)
        GLib.timeout_add(1500, lambda: (self.refresh(), False)[1])


# --------------------------------------------------------------------------- Sound
class SoundPage(Page):
    title, icon = "Sound", "audio-speakers-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Sound", "Speakers, headphones and microphones.")
        self.out_card = ui.card("Output")
        self.in_card = ui.card("Input (microphone)")
        self.body.append(self.out_card)
        self.body.append(self.in_card)
        sp = ui.card("System sounds", "Boot chime, notifications, errors and more come from a sound pack you can "
                     "replace with your own.")
        b = ui.button("Sound packs…", lambda: spawn(["glass-launch", "glass-lens", "--page", "sounds"]))
        b.set_halign(Gtk.Align.START)
        sp.append(b)
        self.body.append(sp)

    def build(self, card, devs, target, kind):
        child = card.get_first_child().get_next_sibling()
        while child:
            nxt = child.get_next_sibling()
            card.remove(child)
            child = nxt
        if not devs:
            card.append(label(f"No {kind} found.", "dim small"))
            return
        cur = next((i for i, d in enumerate(devs) if d[2]), 0)
        dd = dropdown([d[1] for d in devs], cur, lambda i: (run(["wpctl", "set-default", devs[i][0]]),
                                                            GLib.timeout_add(400, lambda: (self.refresh(), False)[1])))
        card.append(ui.setting_row("Device", None, dd))
        vol, muted = get_volume(target)
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        sc.set_draw_value(False)
        sc.set_size_request(260, -1)
        sc.set_value(vol * 100)
        sc.connect("value-changed", lambda s: spawn(["wpctl", "set-volume", target, f"{s.get_value() / 100:.2f}"]))
        card.append(ui.setting_row("Volume", None, sc))
        card.append(ui.setting_row("Mute", None, switch(muted, lambda on: spawn(
            ["wpctl", "set-mute", target, "1" if on else "0"]))))

    def refresh(self):
        d = wpctl_devices()
        self.build(self.out_card, d["sinks"], "@DEFAULT_AUDIO_SINK@", "speakers or headphones")
        self.build(self.in_card, d["sources"], "@DEFAULT_AUDIO_SOURCE@", "microphones")


# --------------------------------------------------------------------------- Appearance
class AppearancePage(Page):
    title, icon = "Appearance", "preferences-desktop-wallpaper-symbolic"
    ACCENTS = ["#6aa8ff", "#9a8cff", "#5fe3a1", "#ffb36b", "#ff7aa8", "#e8e9f0"]

    def __init__(self, win):
        super().__init__(win)
        self.header("Appearance", "Wallpaper and glass.")
        wc = ui.card("Wallpaper")
        self.walls = Gtk.FlowBox()
        self.walls.set_selection_mode(Gtk.SelectionMode.NONE)
        self.walls.set_max_children_per_line(4)
        self.walls.set_column_spacing(10)
        self.walls.set_row_spacing(10)
        self.walls.set_homogeneous(True)
        self.walls.set_halign(Gtk.Align.START)
        wc.append(self.walls)
        b = ui.button("Choose a picture…", self.pick_wallpaper)
        b.set_halign(Gtk.Align.START)
        wc.append(b)
        self.body.append(wc)

        a = ui.appearance()
        gc = ui.card("Glass", "Every window is a pane of glass. Stack windows and the view through them "
                     "gets frostier and darker, layer by layer.")
        self.glass = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.glass.set_draw_value(False)
        self.glass.set_size_request(260, -1)
        self.glass.set_value(a["glass"])
        for v, txt in ((0, "Clear"), (ui.DEFAULTS["glass"], None), (100, "Frosted")):
            self.glass.add_mark(v, Gtk.PositionType.BOTTOM, txt)
        self.glass.connect("value-changed", self.on_glass)
        gc.append(ui.setting_row("Glass", "Clear lets the colours and shapes behind show through. Frosted blurs "
                                 "them away and is easiest to read on.", self.glass))
        sw = hbox(8)
        self.swatches = []
        for col in self.ACCENTS:
            bt = Gtk.Button()
            bt.add_css_class("swatch")
            if col == a["accent"]:
                bt.add_css_class("current")
            prov = Gtk.CssProvider()
            css = f"button {{ background: {col}; }}"
            prov.load_from_string(css) if hasattr(prov, "load_from_string") else prov.load_from_data(css.encode())
            bt.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            bt.connect("clicked", lambda _b, c=col: self.on_accent(c))
            self.swatches.append((col, bt))
            sw.append(bt)
        gc.append(ui.setting_row("Accent color", "Buttons and highlights in GlassOS apps.", sw))
        mode = desktop_conf().get("effects", "auto")
        self.fx = dropdown(["Automatic", "Full glass", "Lighter"],
                           {"auto": 0, "full": 1, "light": 2}.get(mode, 0), self.on_effects)
        self.fx_sub = label(self.effects_note(), "dim small", wrap=True)
        fx_row = ui.setting_row("Effects", None, self.fx)
        fx_row.get_first_child().append(self.fx_sub)
        gc.append(fx_row)
        self.body.append(gc)
        self.body.append(self.dock_card(a))
        self._glass_id = None
        if "frost_vibrancy" not in load_state():
            # set up before the Glass slider (separate Frost and Tint): make the blur match the slider
            self.sync_blur(a["glass"])

    # icon style -> icon theme (drawn by scripts/make-icons.py)
    ICON_STYLES = (("color", "Glass", "Color"), ("clear", "Glass-Clear", "Clear"), ("dark", "Glass-Dark", "Dark"))
    DOCK_PRESETS = {"small": 30, "medium": 36, "large": 46}   # what the old Dock size menu saved

    def dock_card(self, a):
        dc = ui.card("Dock & icons")
        # Icon style, like iPhone's: each choice shows the Settings icon drawn that way
        row = hbox(10)
        self.style_buttons = []
        cur = a.get("icon_style", "dark")
        for key, theme, name in self.ICON_STYLES:
            bt = Gtk.Button()
            bt.add_css_class("icon-style")
            v = vbox(4)
            img = Gtk.Image()
            path = f"/usr/share/icons/{theme}/scalable/apps/glass-files.svg"
            if os.path.exists(path):
                img.set_from_file(path)
            else:
                img.set_from_icon_name("glass-files")
            img.set_pixel_size(48)
            v.append(img)
            v.append(label(name, "small"))
            bt.set_child(v)
            if key == cur:
                bt.add_css_class("current")
            bt.connect("clicked", lambda _b, k=key: self.on_icon_style(k))
            self.style_buttons.append((key, bt))
            row.append(bt)
        dc.append(ui.setting_row("Icon style", "Color, clear glass that lets the wallpaper through, "
                                 "or dark.", row))

        size = a.get("dock_icon")
        if not isinstance(size, (int, float)) or isinstance(size, bool):
            size = self.DOCK_PRESETS.get(a.get("dock_size"), 36)
        self.dock_size = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 24, 72, 1)
        self.dock_size.set_draw_value(False)
        self.dock_size.set_size_request(260, -1)
        self.dock_size.set_value(size)
        for v, txt in ((24, "Small"), (36, None), (72, "Large")):
            self.dock_size.add_mark(v, Gtk.PositionType.BOTTOM, txt)
        self.dock_size.connect("value-changed", lambda s: self.save_later("dock_icon", int(s.get_value())))
        dc.append(ui.setting_row("Dock size", None, self.dock_size))

        dc.append(ui.setting_row(
            "Animate icons on hover", "The icon under the pointer lifts a little.",
            switch(bool(a.get("dock_hover", True)), lambda on: ui.save_appearance(dock_hover=on))))

        dc.append(ui.setting_row(
            "Hide the dock automatically",
            "Move the pointer to the bottom edge of the screen to bring it back. It also hides while a "
            "window is full size.",
            switch(bool(a.get("dock_autohide", False)), lambda on: ui.save_appearance(dock_autohide=on))))
        self._save_ids = {}
        return dc

    def save_later(self, key, value):
        """Sliders save a moment after they stop moving, so the dock isn't redrawn on every step."""
        old = self._save_ids.pop(key, None)
        if old:
            GLib.source_remove(old)

        def save():
            self._save_ids.pop(key, None)
            ui.save_appearance(**{key: value})
            return False
        self._save_ids[key] = GLib.timeout_add(150, save)

    def on_icon_style(self, key):
        theme = dict((k, t) for k, t, _n in self.ICON_STYLES)[key]
        for k, b in self.style_buttons:
            (b.add_css_class if k == key else b.remove_css_class)("current")
        ui.save_appearance(icon_style=key)       # the dock follows appearance.json
        Gtk.Settings.get_default().set_property("gtk-icon-theme-name", theme)
        set_icon_theme(theme)

    @staticmethod
    def effects_note():
        accel = None
        try:
            m = re.search(r"acceleration: (yes|no)", open(os.path.join(CFG, "hypr", "machine.lua")).read())
            accel = m and m.group(1) == "yes"
        except OSError:
            pass
        if accel is None:
            return "Lighter effects use less of the processor, for computers without graphics acceleration."
        if accel:
            return "This computer has graphics acceleration, so Automatic uses full glass."
        return ("No graphics acceleration was found (usual in a virtual machine), so Automatic uses lighter "
                "glass to keep things smooth.")

    def on_effects(self, i):
        mode = ["auto", "full", "light"][i]
        set_desktop_conf("effects", mode)
        p = os.path.join(CFG, "hypr", "machine.lua")
        try:
            text = open(p).read()
            m = re.search(r"acceleration: (yes|no)", text)
            light = mode == "light" or (mode == "auto" and m is not None and m.group(1) == "no")
            text = re.sub(r"return \{ light = (true|false) \}", f"return {{ light = {'true' if light else 'false'} }}", text)
            with open(p, "w") as f:
                f.write(text)
            spawn(["hyprctl", "reload", "config-only"])
        except OSError:
            pass

    def refresh(self):
        ui.clear(self.walls)
        cur = ""
        try:
            for line in open(os.path.join(CFG, "glassos", "desktop.conf")):
                if line.startswith("wallpaper"):
                    cur = line.split("=", 1)[1].strip()
        except OSError:
            cur = "/usr/share/glassos/wallpapers/prism.jpg"
        files = sorted(glob.glob("/usr/share/glassos/wallpapers/*.jpg")) + \
            sorted(glob.glob(os.path.join(HOME, "Pictures", "Wallpapers", "*.*")))
        for f in files[:24]:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(f, 200, 113, False)
            except GLib.Error:
                continue
            pic = Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(pb))
            pic.set_size_request(200, 113)
            pic.add_css_class("wall-thumb")
            if f == cur:
                pic.add_css_class("current")
            btn = Gtk.Button()
            btn.set_child(pic)
            btn.add_css_class("flat")
            btn.set_tooltip_text(os.path.basename(f))
            btn.connect("clicked", lambda _b, p=f: self.set_wallpaper(p))
            self.walls.append(btn)

    def set_wallpaper(self, path):
        run(["glass-wallpaper", path])
        GLib.timeout_add(300, lambda: (self.refresh(), False)[1])

    def pick_wallpaper(self):
        dlg = Gtk.FileDialog(title="Choose a wallpaper")
        f = Gtk.FileFilter()
        f.set_name("Pictures")
        for mt in ("image/jpeg", "image/png", "image/webp"):
            f.add_mime_type(mt)
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dlg.set_filters(store)

        def done(d, res):
            try:
                file = d.open_finish(res)
            except GLib.Error:
                return
            self.set_wallpaper(file.get_path())

        dlg.open(self.win, None, done)

    BLUR_KEYS = ("frost_size", "frost_passes", "frost_vibrancy", "frost_brightness", "frost_noise")

    @classmethod
    def sync_blur(cls, level):
        """Write Hyprland's blur for a Glass level (it reloads its config when this is saved)."""
        look = ui.glass_look(level)
        save_state({k: look[k] for k in cls.BLUR_KEYS})
        return look

    def on_glass(self, s):
        if self._glass_id:
            GLib.source_remove(self._glass_id)

        def apply():
            v = int(s.get_value())
            look = self.sync_blur(v)                           # Hyprland's blur
            ui.save_appearance(glass=v, tint=look["tint"])     # GlassOS apps and the dock
            ui.reload_css()                                    # and this window, straight away
            self._glass_id = None
            return False

        self._glass_id = GLib.timeout_add(250, apply)

    def on_accent(self, col):
        ui.save_appearance(accent=col)
        ui.reload_css()
        for c, b in self.swatches:
            (b.add_css_class if c == col else b.remove_css_class)("current")


# --------------------------------------------------------------------------- Input
def xkb_layouts():
    out, on = [], False
    try:
        for line in open("/usr/share/X11/xkb/rules/evdev.lst"):
            if line.startswith("! "):
                on = line.strip() == "! layout"
                continue
            if on and line.strip():
                code, _, name = line.strip().partition(" ")
                out.append((code, name.strip()))
    except OSError:
        out = [("us", "English (US)")]
    return sorted(out, key=lambda x: x[1])


class InputPage(Page):
    title, icon = "Mouse & Keyboard", "input-keyboard-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Mouse & Keyboard")
        st = load_state()
        mc = ui.card("Mouse and touchpad")
        sp = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -1, 1, 0.05)
        sp.set_draw_value(False)
        sp.set_size_request(240, -1)
        sp.set_value(st.get("sensitivity", 0))
        sp.add_mark(0, Gtk.PositionType.BOTTOM, None)
        self._sp_id = None

        def sp_changed(s):
            if self._sp_id:
                GLib.source_remove(self._sp_id)
            self._sp_id = GLib.timeout_add(300, lambda: (save_state({"sensitivity": round(s.get_value(), 2)}),
                                                         setattr(self, "_sp_id", None), False)[2])

        sp.connect("value-changed", sp_changed)
        mc.append(ui.setting_row("Pointer speed", None, sp))
        mc.append(ui.setting_row("Natural scrolling (touchpad)", "Content moves with your fingers.",
                                 switch(st.get("touchpad_natural_scroll", True),
                                        lambda v: save_state({"touchpad_natural_scroll": v}))))
        mc.append(ui.setting_row("Natural scrolling (mouse wheel)", None,
                                 switch(st.get("mouse_natural_scroll", False),
                                        lambda v: save_state({"mouse_natural_scroll": v}))))
        mc.append(ui.setting_row("Tap to click", "Tap the touchpad instead of pressing it.",
                                 switch(st.get("tap_to_click", True), lambda v: save_state({"tap_to_click": v}))))
        self.body.append(mc)
        kc = ui.card("Keyboard")
        self.layouts = xkb_layouts()
        cur = st.get("kb_layout", "us")
        idx = next((i for i, (c, _) in enumerate(self.layouts) if c == cur), 0)
        dd = dropdown([n for _, n in self.layouts], idx,
                      lambda i: save_state({"kb_layout": self.layouts[i][0], "kb_variant": ""}), search=True)
        kc.append(ui.setting_row("Layout", "Type to search.", dd))
        b = ui.button("Keyboard shortcuts…", lambda: self.win.show_page("shortcuts"))
        kc.append(ui.setting_row("Shortcuts", "Windows, Linux or Mac keys, or your own.", b))
        self.body.append(kc)


# --------------------------------------------------------------------------- Keyboard shortcuts
class KeyCapture(Gtk.Window):
    """Asks for a new shortcut: press it, or type it. done(combo) gets Hyprland's form."""

    MOD_KEYS = {"Super_L": "SUPER", "Super_R": "SUPER", "Meta_L": "SUPER", "Meta_R": "SUPER",
                "Control_L": "CTRL", "Control_R": "CTRL", "Alt_L": "ALT", "Alt_R": "ALT",
                "Shift_L": "SHIFT", "Shift_R": "SHIFT"}

    def __init__(self, parent, action, kind, done):
        super().__init__(transient_for=parent, modal=True, title="Change shortcut")
        self.add_css_class("glass")
        self.set_default_size(440, -1)
        self.kind, self.done, self.combo = kind, done, None
        self.other_key = False  # a non-modifier key was pressed since Super went down
        body = vbox(14, "page")
        body.append(label(glasskeys.DESC[action], "card-title"))
        hint = {"n": "Hold the keys to use with 1–9 and press any number.",
                "dir": "Hold the keys to use with the arrow keys and press any arrow."}.get(
            kind, "Press the keys together. To use a tap of Super on its own, press Super and let go.")
        body.append(label(hint, "dim", wrap=True))
        self.shown = label("Waiting for keys…", "kbd big-kbd", xalign=0.5)
        body.append(self.shown)
        body.append(label("Or type it, like Ctrl + Alt + T:", "dim small"))
        self.entry = Gtk.Entry()
        self.entry.connect("activate", lambda *_: self.save())
        body.append(self.entry)
        self.err = label("", "dim small", wrap=True)
        body.append(self.err)
        row = hbox(8)
        row.append(ui.spacer())
        row.append(ui.button("Cancel", self.close))
        row.append(ui.button("Save", self.save))
        body.append(row)
        self.set_child(body)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_press)
        keys.connect("key-released", self.on_release)
        self.add_controller(keys)
        # While this is open, ask the desktop to pass every key here instead of acting on it
        # (otherwise pressing Super+L to set "lock screen" would lock the screen)
        self.connect("map", lambda *_: self.inhibit(True))
        self.connect("close-request", lambda *_: (self.inhibit(False), False)[1])

    def inhibit(self, on):
        try:
            surf = self.get_surface()
            if on:
                surf.inhibit_system_shortcuts(None)
            else:
                surf.restore_system_shortcuts()
        except Exception:
            pass

    @staticmethod
    def mods_of(state):
        m = []
        if state & (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.META_MASK):
            m.append("SUPER")
        if state & Gdk.ModifierType.CONTROL_MASK:
            m.append("CTRL")
        if state & Gdk.ModifierType.ALT_MASK:
            m.append("ALT")
        if state & Gdk.ModifierType.SHIFT_MASK:
            m.append("SHIFT")
        return m

    def on_press(self, ctl, keyval, keycode, state):
        mods = self.mods_of(state)
        focus = self.get_focus()  # (the entry's inner text widget, in GTK 4)
        typing = focus is not None and (focus == self.entry or focus.is_ancestor(self.entry))
        if typing and not set(mods) - {"SHIFT"}:
            return False  # typing in the box (Shift too, for "+")
        name = Gdk.keyval_name(keyval) or ""
        if name in self.MOD_KEYS:
            if self.MOD_KEYS[name] not in mods:
                mods.append(self.MOD_KEYS[name])
            if mods == ["SUPER"]:
                self.other_key = False
            held = [m for m in glasskeys.MODS if m in mods]
            self.shown.set_text(" + ".join(glasskeys.pretty_key(m) for m in held) + " + …")
            return True
        self.other_key = True
        # the key as it is without Shift (so Shift+1 is "1", not "!")
        found = ctl.get_widget().get_display().translate_key(keycode, 0, 0)
        base = found[1] if found and found[0] else keyval
        key = Gdk.keyval_name(Gdk.keyval_to_lower(base)) or name
        if self.kind == "n":
            if not key.isdigit():
                return True
            key = "{n}"
        elif self.kind == "dir":
            if key.lower() not in ("left", "right", "up", "down"):
                return True
            key = "{dir}"
        plain_ok = key == "Print" or (key[:1] == "F" and key[1:].isdigit())
        if not mods and not plain_ok:
            self.err.set_text("Use at least one of Super, Ctrl or Alt, so the key still types normally.")
            return True
        self.set_combo(glasskeys.normalize(" + ".join(mods + [key])))
        return True

    def on_release(self, ctl, keyval, keycode, state):
        name = Gdk.keyval_name(keyval) or ""
        others = set(self.mods_of(state)) - {"SUPER"}
        if name in ("Super_L", "Super_R") and not self.other_key and not others and self.kind == "":
            self.set_combo("SUPER")
        elif self.combo is None and not self.mods_of(state):
            self.shown.set_text("Waiting for keys…")

    def set_combo(self, combo):
        if not combo:
            return
        self.combo = combo
        self.err.set_text("")
        self.shown.set_text(glasskeys.pretty(combo))
        self.entry.set_text("")

    def save(self):
        typed = self.entry.get_text().strip()
        combo = self.combo
        if typed:
            combo = glasskeys.normalize(typed)
            if combo and self.kind == "n" and "{n}" not in combo:
                combo = None
            if combo and self.kind == "dir" and "{dir}" not in combo:
                combo = None
            if not combo:
                example = {"n": "Super + Shift + {n}", "dir": "Super + Alt + {dir}"}.get(self.kind, "Ctrl + Alt + T")
                self.err.set_text(f"That isn't a shortcut GlassOS understands. Write it like {example}.")
                return
        if not combo:
            self.err.set_text("Press a shortcut first.")
            return
        self.inhibit(False)
        self.done(combo)
        self.destroy()


class ShortcutsPage(Page):
    title, icon = "Keyboard Shortcuts", "preferences-desktop-keyboard-shortcuts-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Keyboard Shortcuts", "Pick the keys you're used to. Super is the Windows key, or ⌘ Command "
                    "on a Mac keyboard; Alt is ⌥ Option.")
        sc = ui.card("Style")
        styles = hbox(8)
        self.style_btn = {}
        for sid, name, _d in glasskeys.STYLES:
            b = ui.button(name, lambda s=sid: self.pick(s), "pill style-pick")
            self.style_btn[sid] = b
            styles.append(b)
        sc.append(styles)
        self.style_desc = label("", "dim", wrap=True)
        sc.append(self.style_desc)
        self.actions_row = hbox(8)
        sc.append(self.actions_row)
        self.body.append(sc)
        self.list = vbox(14)
        self.body.append(self.list)
        self.refresh()

    @staticmethod
    def state():
        st = load_state()
        return st, glasskeys.current_preset(st), glasskeys.effective(st)

    def apply(self, changes):
        st = save_state(changes)  # (reloads the desktop too, but glass-keys.lua must be written first)
        glasskeys.write_lua(glasskeys.effective(st), glasskeys.current_preset(st))
        spawn(["hyprctl", "reload", "config-only"])
        self.refresh()

    def pick(self, sid):
        st, cur, keys = self.state()
        if sid == cur:
            return
        ch = {"keys_preset": sid}
        if sid == "custom" and not st.get("keys_custom"):
            ch["keys_custom"] = keys  # start your own set from the style you had
        self.apply(ch)

    def set_keys(self, aid, combos):
        _st, _cur, keys = self.state()
        keys[aid] = combos
        self.apply({"keys_preset": "custom", "keys_custom": keys})

    def capture(self, aid, add):
        def done(combo):
            _st, _cur, keys = self.state()
            old = keys.get(aid, [])
            if add:
                if combo not in old:
                    self.set_keys(aid, old + [combo])
            else:
                self.set_keys(aid, [combo])
        KeyCapture(self.win, aid, glasskeys.KIND[aid], done).present()

    def refresh(self):
        _st, cur, keys = self.state()
        for sid, b in self.style_btn.items():
            (b.add_css_class if sid == cur else b.remove_css_class)("current")
        self.style_desc.set_text(next(d for s, _n, d in glasskeys.STYLES if s == cur))
        ui.clear(self.actions_row)
        custom = cur == "custom"
        if custom:
            ids = [s for s, _n, _d in glasskeys.STYLES if s != "custom"]
            dd = dropdown([n for s, n, _d in glasskeys.STYLES if s != "custom"], 0)
            self.actions_row.append(label("Start over from", "dim"))
            self.actions_row.append(dd)
            self.actions_row.append(ui.button("Reset", lambda: self.apply(
                {"keys_preset": "custom", "keys_custom": glasskeys.PRESETS[ids[dd.get_selected()]]})))
        else:
            self.actions_row.append(ui.button("Customize these…", lambda: self.apply(
                {"keys_preset": "custom", "keys_custom": keys})))
        clash = glasskeys.clashes(keys)
        ui.clear(self.list)
        for section in glasskeys.SECTIONS:
            c = ui.card(section)
            for aid, sec, desc, _kind in glasskeys.ACTIONS:
                if sec != section:
                    continue
                right = hbox(6)
                combos = keys.get(aid, [])
                if not combos:
                    right.append(label("None", "dim"))
                for combo in combos:
                    right.append(label(glasskeys.pretty(combo), "kbd"))
                if custom:
                    right.append(ui.button("Change", lambda a=aid: self.capture(a, False)))
                    right.append(ui.icon_button("list-add-symbolic", lambda a=aid: self.capture(a, True),
                                                "Add another shortcut"))
                    if combos:
                        right.append(ui.icon_button("edit-clear-symbolic", lambda a=aid: self.set_keys(a, []),
                                                    "Remove its shortcut"))
                sub = None
                if aid in clash:
                    sub = "⚠ Same keys as: " + ", ".join(glasskeys.DESC[o] for o in clash[aid])
                c.append(ui.setting_row(desc, sub, right))
            self.list.append(c)
        if cur == "macos":
            self.list.append(label("In the macOS style, Ctrl + ← / → switch desktops, so apps can't use them to "
                                   "jump between words. Choose Custom to change that.", "dim small", wrap=True))


# --------------------------------------------------------------------------- Date & time
class TimePage(Page):
    title, icon = "Date & Time", "preferences-system-time-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Date & Time")
        c = ui.card()
        self.clock = label("", "clock-big")
        self.date = label("", "dim")
        c.append(self.clock)
        c.append(self.date)
        self.body.append(c)
        s = ui.card()
        _, tzs, _ = run(["timedatectl", "list-timezones"])
        self.tzs = tzs.split() or ["Etc/UTC"]
        _, cur, _ = run(["timedatectl", "show", "-p", "Timezone", "--value"])
        cur = cur.strip() or "Etc/UTC"
        idx = self.tzs.index(cur) if cur in self.tzs else 0
        self.msg = label("", "small warn", wrap=True)
        self.tz_dd = dropdown([t.replace("_", " ") for t in self.tzs], idx, self.on_tz, search=True)
        s.append(ui.setting_row("Time zone", "Type a city to search.", self.tz_dd))
        _, ntp, _ = run(["timedatectl", "show", "-p", "NTP", "--value"])
        s.append(ui.setting_row("Set time automatically",
                                "Asks a public time server (no personal data is sent).",
                                switch(ntp.strip() == "yes", lambda v: self.timedate(["set-ntp", "true" if v else "false"]))))
        fmt24 = False
        try:
            fmt24 = "%H:%M" in open(WAYBAR).read()
        except OSError:
            pass
        s.append(ui.setting_row("24-hour clock", None, switch(fmt24, self.on_24h)))
        s.append(self.msg)
        self.body.append(s)
        self.tick()
        GLib.timeout_add(1000, self.tick)

    def tick(self):
        self.clock.set_text(time.strftime("%H:%M:%S"))
        self.date.set_text(time.strftime("%A, %B %-d, %Y · %Z"))
        return True

    def timedate(self, args):
        def done(res):
            code, _out, err = res
            self.msg.set_text("" if code == 0 else f"Couldn't change it: {err.strip()}")
        bg(lambda: run(["timedatectl"] + args, 30), done)

    def on_tz(self, i):
        tz = self.tzs[i]
        self.timedate(["set-timezone", tz])
        os.environ["TZ"] = tz
        time.tzset()

    def on_24h(self, on):
        try:
            s = open(WAYBAR).read()
        except OSError:
            return
        if on:
            s = s.replace("%-I:%M %p", "%H:%M")
        else:
            s = s.replace("%H:%M", "%-I:%M %p")
        with open(WAYBAR, "w") as f:
            f.write(s)
        spawn(["pkill", "-SIGUSR2", "-x", "waybar"])


# --------------------------------------------------------------------------- Power
IDLE_CHOICES = [(60, "1 minute"), (120, "2 minutes"), (300, "5 minutes"), (600, "10 minutes"),
                (900, "15 minutes"), (1800, "30 minutes"), (3600, "1 hour"), (0, "Never")]


def write_hypridle(dim, lock, off, sleep=900):
    parts = ["# GlassOS idle behaviour. Written by Settings > Power & Lock.",
             "general {",
             "    lock_cmd = pidof hyprlock || glass-lock",
             "    before_sleep_cmd = loginctl lock-session",
             "    after_sleep_cmd = hyprctl dispatch 'hl.dsp.dpms({action = \"on\"})'",
             "}", ""]
    if dim:
        parts += ["listener {", f"    timeout = {dim}", "    on-timeout = brightnessctl -s set 30%",
                  "    on-resume = brightnessctl -r", "}", ""]
    if lock:
        parts += ["listener {", f"    timeout = {lock}", "    on-timeout = loginctl lock-session", "}", ""]
    if off:
        parts += ["listener {", f"    timeout = {off}",
                  "    on-timeout = hyprctl dispatch 'hl.dsp.dpms({action = \"off\"})'",
                  "    on-resume = hyprctl dispatch 'hl.dsp.dpms({action = \"on\"})'", "}", ""]
    if sleep:
        parts += ["listener {", f"    timeout = {sleep}",
                  "    on-timeout = /usr/lib/glassos/sleep-on-battery", "}", ""]
    with open(IDLE, "w") as f:
        f.write("\n".join(parts))
    run(["pkill", "-x", "hypridle"])
    spawn(["systemd-run", "--user", "--scope", "--quiet", "--collect", "--slice=glass-desktop.slice",
           f"--unit=glass-idle-{os.getpid()}-{int(time.time())}", "hypridle"])


class PowerPage(Page):
    title, icon = "Power & Lock", "system-shutdown-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Power & Lock", "What happens when you step away.")
        st = {"dim": 300, "lock": 600, "off": 660, "sleep": 900, **load_state().get("idle", {})}
        c = ui.card()
        self.sel = {}
        labels = [t for _, t in IDLE_CHOICES]

        def idx(v):
            return next((i for i, (s, _) in enumerate(IDLE_CHOICES) if s == v), len(IDLE_CHOICES) - 1)

        for key, title, sub in (("dim", "Dim the screen after", None),
                                ("lock", "Lock after", "You'll need your password to get back in."),
                                ("off", "Turn the screen off after", None),
                                ("sleep", "On battery, sleep after", "Plugged in, the computer stays awake.")):
            v = st.get(key, 0)
            if key == "off" and v == 660:
                v = 900
            dd = dropdown(labels, idx(v), lambda _i: self.apply())
            self.sel[key] = dd
            c.append(ui.setting_row(title, sub, dd))
        self.body.append(c)
        self.bat = ui.card("Battery")
        self.bat_l = label("", "small")
        self.bat.append(self.bat_l)
        self.body.append(self.bat)

    def apply(self):
        vals = {k: IDLE_CHOICES[dd.get_selected()][0] for k, dd in self.sel.items()}
        save_state({"idle": vals})
        write_hypridle(vals["dim"], vals["lock"], vals["off"], vals["sleep"])

    def refresh(self):
        try:
            import sysinfo as si
            bats = si.batteries()
        except Exception:
            bats = []
        self.bat.set_visible(bool(bats))
        if bats:
            b = bats[0]
            txt = f"{b['capacity']}% · {b['status']}"
            if b.get("health"):
                txt += f" · health {b['health']:.0f}% of when it was new"
            self.bat_l.set_text(txt)


# --------------------------------------------------------------------------- Privacy
OWN_SOUNDS = {"pw-play", "paplay", "aplay", "play", "glass-sound", "glass-soundd"}
NOT_APPS = {"pipewire", "wireplumber", "pipewire-pulse", "xdg-desktop-portal", "xdg-desktop-portal-hyprland"}
NICE = {"firefox-esr": "Firefox", "firefox": "Firefox", "glass-browser": "Glass Browser",
        "WebKitWebProcess": "Glass Browser"}


def live_usage():
    """Who is using the camera, microphone, speakers or screen right now:
    [{"kind": "camera"|"mic"|"out"|"screen", "app": name, "pids": [int, ...]}, ...]"""
    found = {}

    def add(kind, app, pid):
        app = NICE.get(app, app)
        pids = found.setdefault((kind, app), [])
        if pid and pid not in pids:
            pids.append(pid)

    for fd in glob.glob("/proc/[0-9]*/fd/*"):
        try:
            if os.readlink(fd).startswith("/dev/video"):
                pid = fd.split("/")[2]
                comm = open(f"/proc/{pid}/comm").read().strip()
                if comm not in NOT_APPS:
                    add("camera", comm, int(pid))
        except OSError:
            continue
    code, out, _ = run(["pw-dump"], 5)
    try:
        objs = json.loads(out) if code == 0 else []
    except ValueError:
        objs = []
    # a stream node only names its app; the process details sit on the client that owns it
    clients = {o.get("id"): (o.get("info") or {}).get("props") or {}
               for o in objs if o.get("type") == "PipeWire:Interface:Client"}
    for o in objs:
        info = o.get("info") or {}
        props = info.get("props") or {}
        if o.get("type") != "PipeWire:Interface:Node" or info.get("state") != "running":
            continue
        client = clients.get(props.get("client.id"), {})
        cls = props.get("media.class", "")
        binary = props.get("application.process.binary") or client.get("application.process.binary", "")
        app = props.get("application.name") or binary or "An app"
        try:
            # pipewire.sec.pid is filled in by PipeWire itself, so an app can't fake it
            pid = int(client.get("pipewire.sec.pid") or client.get("application.process.id"))
        except (TypeError, ValueError):
            pid = None
        if cls == "Stream/Input/Audio":
            add("mic", app, pid)
        elif cls == "Stream/Output/Audio" and binary not in OWN_SOUNDS and app not in OWN_SOUNDS:
            add("out", app, pid)
        elif cls == "Video/Source" and "xdph" in props.get("node.name", ""):
            add("screen", "Screen sharing", None)
        elif cls == "Stream/Input/Video":
            add("camera", app, pid)
    order = {"camera": 0, "mic": 1, "screen": 2, "out": 3}
    return sorted(({"kind": k, "app": a, "pids": p} for (k, a), p in found.items()),
                  key=lambda u: (order[u["kind"]], u["app"].lower()))


class PrivacyPage(Page):
    title, icon = "Privacy & Security", "security-high-symbolic"
    KIND = {"camera": ("camera-web-symbolic", "Using the camera"),
            "mic": ("audio-input-microphone-symbolic", "Using the microphone"),
            "screen": ("video-display-symbolic", "Sharing your screen"),
            "out": ("audio-speakers-symbolic", "Playing sound")}

    def __init__(self, win):
        super().__init__(win)
        self.header("Privacy & Security", "What's using your camera, microphone, speakers and screen right "
                    "now, and a switch to turn each one off.")
        self.now = ui.card("Right now")
        self.now_rows = vbox(6)
        self.now.append(self.now_rows)
        self.body.append(self.now)
        self._last_usage = None

        sw = ui.card("Camera and microphone")
        self._quiet = False
        self.cam_sw = switch(True, self.set_camera)
        sw.append(ui.setting_row("Let apps use the camera", "When this is off, the webcam is switched off for "
                                 "every app, and stays off after a restart.", self.cam_sw))
        self.mic_sw = switch(True, self.set_mic)
        sw.append(ui.setting_row("Let apps use the microphone", "When this is off, every microphone is muted, "
                                 "including ones you plug in later.", self.mic_sw))
        self.sw_note = label("", "small warn", wrap=True)
        self.sw_note.set_visible(False)
        sw.append(self.sw_note)
        self.fw = label("", "small")
        sw.append(ui.setting_row("Firewall", "Blocks connections from outside that you didn't start.", self.fw))
        self.body.append(sw)

        facts = ui.card("How GlassOS is set up")
        for t, d in [("Telemetry", "Not installed, so there's no switch for it."),
                     ("Location", "GlassOS has no location service. Websites have to ask the browser first."),
                     ("Updates", "Installed only when you start them."),
                     ("Accounts", "Just the user accounts on this computer. There's no online sign-in."),
                     ("App Store", "Talks to flathub.org only while it's open. Flathub counts downloads, "
                      "not who you are.")]:
            facts.append(ui.setting_row(t, d, Gtk.Box()))
        self.body.append(facts)
        files = ui.card("Recent files")
        enabled = self.recent_enabled()
        files.append(ui.setting_row("Remember files I open", "Shown in Files and file pickers.",
                                    switch(enabled, self.set_recent)))
        files.append(ui.setting_row("Clear the list now", None, ui.button("Clear", self.clear_recent)))
        self.body.append(files)
        lb = ui.button("See every app and connection in Glass Lens",
                       lambda: spawn(["glass-launch", "glass-lens", "--page", "network"]), "pill accent")
        lb.set_halign(Gtk.Align.START)
        self.body.append(lb)
        GLib.timeout_add_seconds(2, self.refresh_live)

    def refresh(self):
        self._last_usage = None
        self.refresh_live()

        def done(res):
            if isinstance(res, Exception):
                return
            cam, mic = res
            self._quiet = True
            self.cam_sw.set_active(cam != "off")
            self.mic_sw.set_active(mic != "off")
            self._quiet = False

        bg(lambda: (run(["glass-privacy", "camera", "status"])[1].strip(),
                    run(["glass-privacy", "mic", "status"])[1].strip()), done)

    def refresh_live(self):
        if not self.get_mapped():
            return True

        def done(res):
            if isinstance(res, Exception):
                return
            usage, fw = res
            self.fw.set_text("On" if fw else "Off")
            key = [(u["kind"], u["app"], tuple(u["pids"])) for u in usage]
            if key == self._last_usage:
                return
            self._last_usage = key
            ui.clear(self.now_rows)
            if not usage:
                self.now_rows.append(label("Nothing is using your camera, microphone, speakers or screen.", "dim"))
                return
            for u in usage:
                icon, what = self.KIND[u["kind"]]
                r = hbox(12, "row")
                img = Gtk.Image.new_from_icon_name(icon)
                img.set_pixel_size(20)
                r.append(img)
                t = vbox(2)
                t.set_hexpand(True)
                t.append(label(u["app"]))
                t.append(label(what, "dim small"))
                r.append(t)
                if u["kind"] == "screen":
                    b = ui.button("Stop sharing", lambda: self.stop_screen())
                elif u["pids"]:
                    b = ui.button("Quit app", lambda pids=u["pids"]: self.quit_app(pids))
                    b.set_tooltip_text("Closes the app. Save your work in it first.")
                else:
                    b = None
                if b:
                    b.set_valign(Gtk.Align.CENTER)
                    r.append(b)
                self.now_rows.append(r)

        bg(lambda: (live_usage(), run(["systemctl", "is-active", "nftables"])[1].strip() == "active"), done)
        return True

    def quit_app(self, pids):
        for pid in pids:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        self._last_usage = None
        GLib.timeout_add(800, lambda: (self.refresh_live(), False)[1])

    def stop_screen(self):
        # Every screen share goes through the desktop portal; restarting it ends them all.
        run(["systemctl", "--user", "restart", "xdg-desktop-portal-hyprland"])
        self._last_usage = None
        GLib.timeout_add(800, lambda: (self.refresh_live(), False)[1])

    def note(self, text):
        self.sw_note.set_text(text)
        self.sw_note.set_visible(bool(text))

    def set_camera(self, on):
        if self._quiet:
            return
        self.note("")

        def done(res):
            if isinstance(res, Exception):
                res = (1, "", str(res))
            code, out, err = res
            if code == 0:
                return
            if code == 2 or "busy" in out:
                self.note("The camera is in use. Quit the app using it, then switch the camera off again.")
            else:
                self.note("Couldn't switch the camera " + ("on" if on else "off") +
                          ". Only admin accounts can change this.")
            self._quiet = True
            self.cam_sw.set_active(not on)
            self._quiet = False

        bg(lambda: run(["sudo", "-n", "/usr/bin/glass-privacy", "camera", "on" if on else "off"]), done)

    def set_mic(self, on):
        if self._quiet:
            return
        self.note("")
        bg(lambda: run(["glass-privacy", "mic", "on" if on else "off"]))

    @staticmethod
    def recent_enabled():
        for v in ("gtk-3.0", "gtk-4.0"):
            try:
                if "gtk-recent-files-enabled=false" in open(os.path.join(CFG, v, "settings.ini")).read().replace(" ", ""):
                    return False
            except OSError:
                pass
        return True

    def set_recent(self, on):
        for v in ("gtk-3.0", "gtk-4.0"):
            p = os.path.join(CFG, v, "settings.ini")
            try:
                lines = [ln for ln in open(p).read().splitlines() if not ln.replace(" ", "").startswith("gtk-recent-files-enabled=")]
            except OSError:
                lines = ["[Settings]"]
            out = []
            for ln in lines:
                out.append(ln)
                if ln.strip() == "[Settings]":
                    out.append(f"gtk-recent-files-enabled={'true' if on else 'false'}")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write("\n".join(out) + "\n")
        if not on:
            self.clear_recent()

    @staticmethod
    def clear_recent():
        try:
            os.remove(os.path.join(HOME, ".local", "share", "recently-used.xbel"))
        except OSError:
            pass


# --------------------------------------------------------------------------- running helpers as root
def as_admin(*argv):
    """The command that runs a GlassOS helper as root: through pkexec, which shows the "type an
    administrator's password" window. Systems set up before pkexec was part of GlassOS fall back
    to sudo, which works without a password only on the live USB (see refused())."""
    import shutil
    if shutil.which("pkexec"):
        return ["pkexec", *argv]
    return ["sudo", "-n", *argv]


def refused(code, output=""):
    """True when the helper didn't run because no administrator said yes: the pkexec password
    window was closed or the password was wrong (126/127), or sudo wanted a password."""
    return code in (126, 127) or "a password is required" in (output or "")


# --------------------------------------------------------------------------- Users
USERS_HELPER = "/usr/lib/glassos/glass-users"   # runs as root through pkexec, which asks for an admin password


def users_admin(args, password=None):
    """Run the account helper as root. polkit shows a password window first. Returns an error
    message for people, or None when it worked."""
    try:
        r = subprocess.run(as_admin(USERS_HELPER, *args), input=(password or "") + "\n",
                           capture_output=True, text=True, timeout=300)
    except Exception as e:
        return str(e)
    if r.returncode == 0:
        return None
    if refused(r.returncode, r.stderr):
        return "Nothing was changed: an administrator's password is needed."
    return (r.stderr or r.stdout).strip() or "Something went wrong."


def people():
    """Accounts people log in to (not system accounts): [(username, full name, is admin)]"""
    try:
        import grp
        admins = set(grp.getgrnam("sudo").gr_mem)
    except KeyError:
        admins = set()
    out = []
    for p in pwd.getpwall():
        if 1000 <= p.pw_uid < 60000 and not p.pw_shell.endswith(("nologin", "false")):
            out.append((p.pw_name, p.pw_gecos.split(",")[0] or p.pw_name, p.pw_name in admins))
    return sorted(out, key=lambda x: x[1].lower())


def account_name(full):
    """"Sarah Connor" -> "sarah": a suggestion; people can change it"""
    first = re.sub(r"[^a-z0-9_-]", "", (full.strip().split() or [""])[0].lower())
    return first if re.match(r"^[a-z_]", first) else ""


class UsersPage(Page):
    title, icon = "Users", "system-users-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Users", "Each person gets their own desktop, files and settings.")
        me = pwd.getpwuid(os.getuid())
        self.me = me.pw_name
        c = ui.card()
        c.append(ui.setting_row(me.pw_gecos.split(",")[0] or me.pw_name, f"Account name: {me.pw_name}", Gtk.Box()))
        c.append(ui.setting_row("Password", None, ui.button("Change…", lambda: self.password_dialog(self.me))))
        self.auto = Gtk.Switch()
        self.auto_id = self.auto.connect("state-set", self.on_autologin)
        c.append(ui.setting_row("Log in automatically", "Skips the password at startup. Anyone who turns on "
                                "this computer gets your desktop.", self.auto))
        self.msg = label("", "dim small", wrap=True)
        c.append(self.msg)
        self.body.append(c)
        self.others = ui.card("Other people")
        self.others_list = vbox(0)
        self.others.append(self.others_list)
        row = hbox(8)
        row.append(ui.spacer())
        row.append(ui.button("Add Person…", self.add_dialog, "pill accent"))
        self.others.append(row)
        self.body.append(self.others)

    def refresh(self):
        try:
            conf = open("/etc/greetd/config.toml").read()
            m = re.search(r"\[initial_session\][^\[]*user\s*=\s*\"([^\"]+)\"", conf)
            on = bool(m and m.group(1) == self.me)
        except OSError:
            on = False
        self.auto.handler_block(self.auto_id)
        self.auto.set_active(on)
        self.auto.set_state(on)
        self.auto.handler_unblock(self.auto_id)
        ui.clear(self.others_list)
        others = [p for p in people() if p[0] != self.me]
        if not others:
            self.others_list.append(label("Only you have an account on this computer.", "dim small"))
        for name, full, admin in others:
            self.others_list.append(ui.setting_row(full, f"{name} · {'Administrator' if admin else 'Standard'}",
                                                   ui.button("Remove…", lambda n=name, f=full: self.remove_dialog(n, f))))

    def after(self, err, ok_text=""):
        self.msg.set_text(err or ok_text)
        self.refresh()

    def on_autologin(self, sw, state):
        def done(err):
            self.after(err, "Automatic login is on." if state else "Automatic login is off.")
        bg(lambda: users_admin(["autologin", self.me, "on" if state else "off"]), done)
        return True   # the switch moves once the change has worked (refresh)

    # ---- small windows
    def dialog(self, title, action_text, on_ok):
        dlg = Gtk.Window(transient_for=self.win, modal=True, title=title)
        dlg.add_css_class("glass")
        dlg.add_css_class("solid")
        dlg.set_default_size(400, -1)
        b = vbox(12)
        for m in ("top", "bottom", "start", "end"):
            getattr(b, f"set_margin_{m}")(20)
        b.append(label(title, "card-title"))
        err = label("", "small warn", wrap=True)
        buttons = hbox(8)
        buttons.append(ui.spacer())
        buttons.append(ui.button("Cancel", dlg.close))
        ok = ui.button(action_text, lambda: on_ok(dlg, err), "pill accent")
        buttons.append(ok)
        dlg.set_child(b)
        return dlg, b, err, buttons

    def password_dialog(self, user):
        def ok(dlg, err):
            p1, p2 = pw1.get_text(), pw2.get_text()
            if not p1:
                err.set_text("Type a password.")
            elif p1 != p2:
                err.set_text("The two passwords don't match.")
            else:
                dlg.close()
                bg(lambda: users_admin(["password", user], p1), lambda e: self.after(e, "Password changed."))
        dlg, b, err, buttons = self.dialog("Change password", "Change", ok)
        pw1 = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="New password")
        pw2 = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Type it again")
        pw2.connect("activate", lambda *_: ok(dlg, err))
        for w in (pw1, pw2, err, buttons):
            b.append(w)
        dlg.present()

    def add_dialog(self):
        def ok(dlg, err):
            full, name = full_e.get_text().strip(), name_e.get_text().strip()
            p1, p2 = pw1.get_text(), pw2.get_text()
            if not full:
                err.set_text("Type the person's name.")
            elif not re.match(r"^[a-z_][a-z0-9_-]{0,31}$", name):
                err.set_text("The account name can use lowercase letters, numbers, - and _, and starts with a letter.")
            elif any(name == p[0] for p in pwd.getpwall()):
                err.set_text(f"There's already an account called {name}.")
            elif not p1:
                err.set_text("Type a password.")
            elif p1 != p2:
                err.set_text("The two passwords don't match.")
            else:
                dlg.close()
                kind = "admin" if admin.get_active() else "standard"
                bg(lambda: users_admin(["add", name, full, kind], p1),
                   lambda e: self.after(e, f"{full} can now log in as {name}."))
        dlg, b, err, buttons = self.dialog("Add a person", "Add Person", ok)
        full_e = Gtk.Entry(placeholder_text="Full name, e.g. Sarah Connor")
        name_e = Gtk.Entry(placeholder_text="Account name, e.g. sarah")
        edited = {"name": False}
        full_e.connect("changed", lambda e: edited["name"] or name_e.set_text(account_name(e.get_text())))
        name_e.connect("changed", lambda e: edited.__setitem__("name", e.has_focus()) if e.has_focus() else None)
        pw1 = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Password")
        pw2 = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Type it again")
        admin = Gtk.Switch()
        b.append(full_e)
        b.append(name_e)
        b.append(pw1)
        b.append(pw2)
        b.append(ui.setting_row("Administrator", "Can install apps, add people and change settings for everyone.", admin))
        b.append(err)
        b.append(buttons)
        dlg.present()

    def remove_dialog(self, user, full):
        def ok(dlg, _err):
            dlg.close()
            bg(lambda: users_admin(["remove", user]), lambda e: self.after(e, f"{full}'s account was removed."))
        dlg, b, err, buttons = self.dialog(f"Remove {full}?", "Remove", ok)
        b.append(label(f"This deletes the account {user} and everything in /home/{user}: documents, "
                       "pictures, settings. It can't be undone.", "small", wrap=True))
        b.append(buttons)
        dlg.present()


# --------------------------------------------------------------------------- Software Update
UPDATES_CHECK = "/usr/lib/glassos/updates-check"      # apt-get update, as root through pkexec (no password)
UPDATES_INSTALL = "/usr/lib/glassos/updates-install"  # apt-get full-upgrade, asks for an admin password
RESTART_FOR = ("linux-image", "glassos-desktop", "libc6", "systemd", "dbus", "hyprland", "firmware-")


def build_info():
    info = {}
    try:
        with open("/usr/share/glassos/build-info") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k:
                    info[k] = v
    except OSError:
        pass
    return info


def update_channel():
    try:
        with open("/etc/glassos/updates.conf") as f:
            for line in f:
                k, _, v = line.partition("=")
                if k.strip() == "channel" and v.strip():
                    return v.strip()
    except OSError:
        pass
    return build_info().get("UPDATE_CHANNEL", "stable")


def last_checked():
    """When the update lists were last refreshed (apt-get update), as a time, or None."""
    stamps = [os.path.getmtime(p) for p in glob.glob("/var/lib/apt/lists/*Release")]
    return max(stamps) if stamps else None


def pending_updates():
    """What "Update Now" would do, worked out without root (apt-get -s simulates).
    -> [{"name", "old", "new", "origin"}], including new packages an update brings in."""
    code, out, err = run(["apt-get", "-s", "-q", "full-upgrade"], 60)
    if code != 0:
        raise RuntimeError((err or out).strip().splitlines()[-1] if (err or out).strip() else "apt-get failed")
    plan = []
    for line in out.splitlines():
        m = re.match(r"Inst (\S+) (?:\[(\S+)\] )?\((\S+) (.*?) \[", line)
        if m:
            plan.append({"name": m.group(1), "old": m.group(2), "new": m.group(3), "origin": m.group(4)})
    return plan


def download_size(plan):
    if not plan:
        return 0
    _, out, _ = run(["apt-cache", "show", "--no-all-versions"] + [f"{p['name']}={p['new']}" for p in plan], 30)
    return sum(int(m) for m in re.findall(r"^Size: (\d+)", out, re.M))


def whats_new(version):
    """The change list GlassOS's build put in the package description (" * ..." lines)."""
    _, out, _ = run(["apt-cache", "show", f"glassos-desktop={version}"], 15)
    return [l.strip()[2:] for l in out.splitlines() if l.startswith(" * ")]


def pretty_version(v):
    """glassos-desktop's version for people: "1:142+1.5.0" -> "1.5.0 (build 142)".
    Older builds were numbered "1.0.0+git28" (-> "1.0.0 (build 28)") or "1.5.0+local2026...". """
    m = re.match(r"(?:\d+:)?(\d+)\+(.+)$", v or "")
    if m:
        return f"{m.group(2)} (build {m.group(1)})"
    m = re.match(r"(?:\d+:)?([^+]+)\+git(\d+)$", v or "")
    if m:
        return f"{m.group(1)} (build {m.group(2)})"
    return (v or "?").split("+")[0]


def human_size(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
        n /= 1000


class UpdatesPage(Page):
    title, icon = "Software Update", "system-software-update-symbolic"

    def __init__(self, win):
        super().__init__(win)
        self.header("Software Update", "GlassOS and the Debian system underneath it (security fixes, the Linux "
                    "kernel, drivers and apps) update together. Nothing is downloaded or installed until you say so.")
        info = build_info()
        top = ui.card()
        row = hbox(14)
        logo = Gtk.Image.new_from_file("/usr/share/glassos/logo.png")
        logo.set_pixel_size(48)
        row.append(logo)
        t = vbox(2)
        t.set_hexpand(True)
        t.set_valign(Gtk.Align.CENTER)
        rel = info.get("GLASSOS_RELEASE") or info.get("GLASSOS_VERSION", "")
        t.append(label(f"GlassOS {rel}", "card-title"))
        chan = update_channel()
        t.append(label(f"Build {info.get('GLASSOS_BUILD_NUMBER') or pretty_version(info.get('GLASSOS_VERSION'))} · "
                       + ("test builds (every change, as soon as it's made)" if chan == "dev" else f"{chan} releases"),
                       "dim small"))
        self.checked = label("", "dim small")
        t.append(self.checked)
        row.append(t)
        self.check_btn = ui.button("Check for Updates", self.check, "pill accent")
        self.check_btn.set_valign(Gtk.Align.CENTER)
        row.append(self.check_btn)
        top.append(row)
        self.status = label("", "small", wrap=True)
        top.append(self.status)
        self.body.append(top)

        self.live = os.path.isdir("/run/live/medium")
        if self.live:
            self.body.append(label("You're running GlassOS from the USB stick: updates work, but they're gone the next "
                                   "time it starts. Install GlassOS to keep them.", "small warn", wrap=True))

        self.list_card = ui.card()
        self.list_card.set_visible(False)
        self.body.append(self.list_card)
        self.plan = []
        self.busy = False

    def refresh(self):
        t = last_checked()
        if t:
            day = time.strftime("%b %-d", time.localtime(t))
            today = time.strftime("%b %-d")
            when = ("today" if day == today else f"on {day}") + time.strftime(" at %-I:%M %p", time.localtime(t))
            self.checked.set_text(f"Last checked {when}")
        else:
            self.checked.set_text("Not checked yet")

    # ---- checking
    def check(self):
        if self.busy:
            return
        self.busy = True
        self.check_btn.set_sensitive(False)
        self.status.set_text("Checking for updates…")
        self.list_card.set_visible(False)

        def work():
            r = subprocess.run(as_admin(UPDATES_CHECK), capture_output=True, text=True, timeout=300)
            if refused(r.returncode, r.stderr):
                return "cancelled", None
            # apt-get update says "W:"/"E:" for servers it couldn't reach; it still uses the rest
            problems = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith(("E:", "Err:"))]
            plan = pending_updates()
            return problems, plan

        bg(work, self.checked_done)

    def checked_done(self, res):
        self.busy = False
        self.check_btn.set_sensitive(True)
        self.refresh()
        if isinstance(res, Exception):
            self.status.set_text(f"Couldn't check for updates: {res}")
            return
        problems, plan = res
        if problems == "cancelled":
            self.status.set_text("Nothing was checked: an administrator's password is needed.")
            return
        self.plan = plan
        note = ""
        if problems:
            note = " Some update servers couldn't be reached (is the internet connected?), so this may not be everything."
        if not plan:
            self.status.set_text("GlassOS is up to date." + note)
            return
        self.status.set_text(note.strip())
        self.show_plan(plan)

    def show_plan(self, plan):
        c = self.list_card
        ui.clear(c)
        c.set_visible(True)
        n = len(plan)
        head = hbox(10)
        t = vbox(2)
        t.set_hexpand(True)
        t.append(label(f"{n} update{'s' if n != 1 else ''} available", "card-title"))
        self.size_lbl = label("", "dim small")
        t.append(self.size_lbl)
        head.append(t)
        self.go_btn = ui.button("Update Now", self.install, "pill accent")
        self.go_btn.set_valign(Gtk.Align.CENTER)
        head.append(self.go_btn)
        c.append(head)
        bg(lambda: download_size(plan), lambda s: self.size_lbl.set_text(
            f"{human_size(s)} to download" if isinstance(s, int) and s else ""))

        glass = [p for p in plan if p["name"] == "glassos-desktop"]
        kernel = [p for p in plan if p["name"].startswith("linux-image")]
        security = [p for p in plan if p not in glass + kernel and "Security" in p["origin"]]
        other = [p for p in plan if p not in glass + kernel + security]
        if glass:
            g = glass[0]
            box = vbox(4, "row")
            box.append(label(f"GlassOS {pretty_version(g['new'])}", "card-title"))
            notes = vbox(2)
            box.append(notes)
            c.append(box)

            def show_notes(lines):
                if isinstance(lines, list) and lines:
                    for l in lines[:12]:
                        notes.append(label(f"•  {l}", "small", wrap=True))
                else:
                    notes.append(label("Improvements to GlassOS's desktop and apps.", "dim small"))
            bg(lambda: whats_new(g["new"]), show_notes)
        if kernel:
            c.append(ui.setting_row("New Linux kernel", f"{kernel[0]['new']}. Takes effect after a restart.",
                                    label("", "dim small")))
        for title, group, sub in (("Security fixes", security, "Fixes for known security problems, from Debian."),
                                  ("System and apps", other, "Bug fixes for the software GlassOS is built on.")):
            if not group:
                continue
            exp = Gtk.Expander(label=f"{title} ({len(group)})")
            inner = vbox(2)
            inner.append(label(sub, "dim small", wrap=True))
            for p in group:
                inner.append(label(f"{p['name']}  {p['old'] or 'new'} → {p['new']}", "mono dim", ellipsize=True))
            exp.set_child(inner)
            c.append(exp)
        self.bar = Gtk.ProgressBar()
        self.bar.set_visible(False)
        c.append(self.bar)
        self.step = label("", "dim small", ellipsize=True)
        c.append(self.step)

    # ---- installing
    def install(self):
        if self.busy:
            return
        self.busy = True
        self.go_btn.set_sensitive(False)
        self.check_btn.set_sensitive(False)
        self.bar.set_visible(True)
        self.bar.set_fraction(0)
        self.step.set_text("Waiting for permission…")
        restart = any(p["name"].startswith(RESTART_FOR) for p in self.plan)

        def work():
            p = subprocess.Popen(as_admin(UPDATES_INSTALL), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, bufsize=1)
            tail = []
            for line in p.stdout:
                line = line.rstrip()
                parts = line.split(":", 3)
                if parts[0] in ("dlstatus", "pmstatus") and len(parts) == 4:
                    try:
                        pct = float(parts[2])
                    except ValueError:
                        continue
                    frac = pct / 100 * 0.35 if parts[0] == "dlstatus" else 0.35 + pct / 100 * 0.65
                    GLib.idle_add(self.progress, frac, parts[3])
                elif line:
                    tail = (tail + [line])[-6:]
            return p.wait(), tail

        def done(res):
            self.busy = False
            self.check_btn.set_sensitive(True)
            if isinstance(res, Exception):
                self.step.set_text(f"Couldn't install the updates: {res}")
                self.go_btn.set_sensitive(True)
                return
            code, tail = res
            if refused(code, "\n".join(tail)):
                self.step.set_text("Nothing was installed: an administrator's password is needed.")
                self.bar.set_visible(False)
                self.go_btn.set_sensitive(True)
                return
            if code != 0:
                err = [l for l in tail if l.startswith("E:")] or tail
                self.step.set_text("The update didn't finish: " + (err[-1] if err else f"error {code}") +
                                   " Nothing you had is lost; try again, and if it keeps failing, restart first.")
                self.step.set_wrap(True)
                self.go_btn.set_sensitive(True)
                return
            self.bar.set_fraction(1)
            self.plan = []
            ui.clear(self.list_card)
            box = vbox(10)
            box.append(label("Updates installed.", "card-title"))
            if restart:
                box.append(label("Restart to finish: the new version of GlassOS (or Linux) starts then.", "dim small",
                                 wrap=True))
                row = hbox(8)
                row.append(ui.button("Restart Now", lambda: spawn(["glass-power", "restart"]), "pill accent"))
                row.append(ui.button("Later", lambda: self.list_card.set_visible(False)))
                box.append(row)
            self.list_card.append(box)
            self.status.set_text("")
            self.refresh()

        bg(work, done)

    def progress(self, frac, text):
        self.bar.set_fraction(max(self.bar.get_fraction(), min(1.0, frac)))
        self.step.set_text(text)
        return False


# --------------------------------------------------------------------------- About
class AboutPage(Page):
    title, icon = "About", "help-about-symbolic"

    def __init__(self, win):
        super().__init__(win)
        try:
            import sysinfo as si
            s = si.system_summary()
            ci = si.cpu_info()
            mem = si.human_bytes(si.meminfo()["MemTotal"])
            gpus = ", ".join(g["name"] for g in si.gpus()) or "Unknown"
            disk = ", ".join(f"{d['model'] or d['name']} ({si.human_bytes(d['size'])})" for d in si.disks()) or "-"
        except Exception:
            s, ci, mem, gpus, disk = {"build": {}, "kernel": os.uname().release, "product": "", "debian": ""}, \
                {"model": "", "arch": os.uname().machine}, "", "", ""
        b = s.get("build", {})
        hero = hbox(18)
        logo = Gtk.Image.new_from_file("/usr/share/glassos/logo.png")
        logo.set_pixel_size(84)
        hero.append(logo)
        t = vbox(2)
        t.set_valign(Gtk.Align.CENTER)
        t.append(label(f"GlassOS {b.get('GLASSOS_RELEASE') or b.get('GLASSOS_VERSION', '')}", "page-title"))
        t.append(label(f"“{b.get('GLASSOS_CODENAME', '')}” · built on Debian {s.get('debian', '')}", "dim"))
        hero.append(t)
        self.body.append(hero)
        c = ui.card()
        for k, v in (("Computer", s.get("product") or "Unknown"), ("Processor", f"{ci['model']} ({ci['arch']})"),
                     ("Memory", mem), ("Graphics", gpus), ("Storage", disk), ("Linux kernel", s.get("kernel", ""))):
            c.append(ui.setting_row(k, None, label(v, "dim small", selectable=True, wrap=True)))
        self.body.append(c)
        row = hbox(8)
        row.append(ui.button("What's using my computer", lambda: spawn(["glass-launch", "glass-lens"]), "pill accent"))
        row.append(ui.button("Software Update", lambda: self.win.show_page("updates")))
        row.append(ui.button("Everything that's installed", lambda: spawn(["glass-launch", "glass-lens", "--page", "about"])))
        self.body.append(row)


PAGES = [("network", NetworkPage), ("bluetooth", BluetoothPage), ("displays", DisplaysPage), ("sound", SoundPage),
         ("appearance", AppearancePage), ("input", InputPage), ("shortcuts", ShortcutsPage), ("time", TimePage), ("power", PowerPage),
         ("privacy", PrivacyPage), ("users", UsersPage), ("updates", UpdatesPage),
         ("about", AboutPage)]


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Settings")
        self.add_css_class("glass")
        ui.fit_size(self, 980, 680)
        hb = Gtk.HeaderBar()
        hb.set_title_widget(label("Settings", "card-title"))
        self.set_titlebar(hb)
        ui.drag_by_titlebar(self, hb)
        root = hbox(0)
        side = vbox(0, "sidebar-pane")
        side.set_size_request(230, -1)
        self.side = Gtk.ListBox()
        self.side.set_selection_mode(Gtk.SelectionMode.SINGLE)
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.set_vexpand(True)
        sc.set_child(self.side)
        side.append(sc)
        root.append(side)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        root.append(self.stack)
        self.set_child(root)
        self.pages, self.rows = {}, {}
        for key, cls in PAGES:
            try:
                page = cls(self)
            except Exception as e:
                page = Page(self)
                page.header(cls.title, f"This page couldn't load: {e}")
            self.pages[key] = page
            self.stack.add_named(page, key)
            r = Gtk.ListBoxRow()
            rb = hbox(10)
            rb.append(Gtk.Image.new_from_icon_name(cls.icon))
            rb.append(label(cls.title))
            r.set_child(rb)
            r.key = key
            self.rows[key] = r
            self.side.append(r)
        self.side.connect("row-selected", lambda _l, r: r and self.show_page(r.key, from_list=True))

    def show_page(self, key, from_list=False):
        if key not in self.pages:
            key = "network"
        self.stack.set_visible_child_name(key)
        if not from_list:
            self.side.select_row(self.rows[key])
        try:
            self.pages[key].refresh()
        except Exception as e:
            print(f"glass-settings: {key}: {e}", file=sys.stderr)


class SettingsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()
        page = args[args.index("--page") + 1] if "--page" in args and args.index("--page") + 1 < len(args) else None
        if self.win is None:
            ui.apply_css(CSS)
            self.win = SettingsWindow(self)
            page = page or "network"
        if page:
            self.win.show_page(page)
        self.win.present()
        return 0


if __name__ == "__main__":
    GLib.set_prgname(APP_ID)
    sys.exit(SettingsApp().run(sys.argv))
