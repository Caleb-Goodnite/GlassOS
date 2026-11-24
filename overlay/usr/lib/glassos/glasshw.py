"""Wi-Fi, Bluetooth and sound helpers shared by Glass Settings and the top bar's drop-downs
(glass-panel). They call the same tools you could run yourself: nmcli, bluetoothctl, wpctl.
"""
import re
import subprocess

from gi.repository import Gio, GLib

NM = "org.freedesktop.NetworkManager"


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:  # missing tool, timeout...
        return 1, "", str(e)


# --------------------------------------------------------------------------- Wi-Fi
def nm_split(line):
    return [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]


def nm_connect_new(ssid, password=None):
    """Add + activate a Wi-Fi connection over D-Bus, so the password never appears in a
    process list (it isn't passed on a command line)."""
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    def call(path, iface, method, args, rtype):
        return bus.call_sync(NM, path, iface, method, args, GLib.VariantType(rtype), Gio.DBusCallFlags.NONE,
                             60000, None).unpack()

    def prop(path, iface, name):
        return call(path, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (iface, name)), "(v)")[0]

    for dev in call("/org/freedesktop/NetworkManager", NM, "GetDevices", None, "(ao)")[0]:
        if prop(dev, NM + ".Device", "DeviceType") != 2:
            continue
        for ap in call(dev, NM + ".Device.Wireless", "GetAllAccessPoints", None, "(ao)")[0]:
            if bytes(prop(ap, NM + ".AccessPoint", "Ssid")).decode(errors="replace") != ssid:
                continue
            settings = {}
            if password:
                settings["802-11-wireless-security"] = {"psk": GLib.Variant("s", password)}
            call("/org/freedesktop/NetworkManager", NM, "AddAndActivateConnection",
                 GLib.Variant("(a{sa{sv}}oo)", (settings, dev, ap)), "(oo)")
            return True
    raise RuntimeError(f"Couldn't find the network \"{ssid}\" any more.")


def wifi_state(rescan=False):
    """Everything the Wi-Fi menu shows, in one go.
    -> {"radio": bool, "adapter": bool, "wired": name or None, "known": set of saved Wi-Fi names,
        "nets": [{"ssid", "signal", "secure", "inuse"}] strongest first, one per name}"""
    _, radio, _ = run(["nmcli", "-t", "-f", "WIFI", "radio"])
    _, devs, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    _, known, _ = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    st = {"radio": radio.strip() == "enabled", "adapter": False, "wired": None, "nets": [],
          "known": {nm_split(l)[0] for l in known.splitlines() if l.endswith(":802-11-wireless")}}
    for line in devs.splitlines():
        p = nm_split(line)
        if len(p) < 4:
            continue
        st["adapter"] |= p[1] == "wifi"
        if p[1] == "ethernet" and p[2] == "connected":
            st["wired"] = p[3]
    if not (st["adapter"] and st["radio"]):
        return st
    _, nets, _ = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                      "--rescan", "yes" if rescan else "no"], timeout=25)
    seen = {}
    for line in nets.splitlines():
        p = nm_split(line)
        if len(p) < 4 or not p[1]:
            continue
        n = {"ssid": p[1], "signal": int(p[2] or 0), "secure": p[3] not in ("", "--"), "inuse": p[0] == "*"}
        old = seen.get(n["ssid"])
        if old is None:
            seen[n["ssid"]] = n
        else:  # the same network from several access points: keep the best reading
            old["inuse"] |= n["inuse"]
            old["signal"] = max(old["signal"], n["signal"])
    st["nets"] = sorted(seen.values(), key=lambda n: -n["signal"])
    return st


def wifi_device_state():
    """The Wi-Fi adapter's state as nmcli words, e.g. "connecting (getting IP configuration)"."""
    _, out, _ = run(["nmcli", "-t", "-f", "TYPE,STATE", "device", "status"], 5)
    for line in out.splitlines():
        p = nm_split(line)
        if len(p) >= 2 and p[0] == "wifi":
            return p[1]
    return ""


def active_state(name):
    """'activated', 'activating', ... for the active connection called name, or None."""
    _, out, _ = run(["nmcli", "-t", "-f", "NAME,STATE", "connection", "show", "--active"], 5)
    for line in out.splitlines():
        p = nm_split(line)
        if len(p) >= 2 and p[0] == name:
            return p[1]
    return None


# --------------------------------------------------------------------------- Bluetooth
def bt_state():
    """None if there's no Bluetooth adapter, else {"powered": bool, "devices": [{"mac", "name",
    "connected"}]} for your paired devices, connected ones first."""
    code, show, err = run(["bluetoothctl", "show"], 5)
    if code != 0 or "No default controller" in show + err:
        return None
    devs = []
    if "Powered: yes" in show:
        _, paired, _ = run(["bluetoothctl", "devices", "Paired"], 5)
        _, conn, _ = run(["bluetoothctl", "devices", "Connected"], 5)
        connected = set(re.findall(r"Device ([0-9A-F:]{17})", conn))
        for m in re.finditer(r"Device ([0-9A-F:]{17}) (.*)", paired):
            devs.append({"mac": m.group(1), "name": m.group(2), "connected": m.group(1) in connected})
    devs.sort(key=lambda d: (not d["connected"], d["name"].lower()))
    return {"powered": "Powered: yes" in show, "devices": devs}


# --------------------------------------------------------------------------- Sound
def wpctl_devices():
    """Parse `wpctl status` -> {'sinks': [(id, name, default)], 'sources': [...]}"""
    _, out, _ = run(["wpctl", "status"])
    res = {"sinks": [], "sources": []}
    section = None
    in_audio = False
    for line in out.splitlines():
        s = line.strip(" │├└─")
        if line.startswith("Audio"):
            in_audio = True
            continue
        if line.startswith(("Video", "Settings")):
            in_audio = False
        if not in_audio:
            continue
        if s.endswith(":"):
            section = {"Sinks:": "sinks", "Sources:": "sources"}.get(s)
            continue
        if section:
            m = re.match(r"(\*)?\s*(\d+)\.\s+(.+?)\s*(\[vol:.*\])?$", s)
            if m:
                res[section].append((m.group(2), m.group(3), bool(m.group(1))))
    return res


def get_volume(target):
    _, out, _ = run(["wpctl", "get-volume", target])
    m = re.search(r"([\d.]+)", out)
    return (float(m.group(1)) if m else 0.0), "MUTED" in out


# --------------------------------------------------------------------------- Display
def brightness():
    """Screen brightness 0-100, or None when the screen has no backlight control (most external
    monitors, and virtual machines)."""
    code, out, _ = run(["brightnessctl", "-m", "-c", "backlight"], 5)
    m = re.search(r",(\d+)%,", out)
    return int(m.group(1)) if code == 0 and m else None
