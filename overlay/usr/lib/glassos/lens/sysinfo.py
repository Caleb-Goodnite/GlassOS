"""Glass Lens data layer: reads the kernel's own accounting (cgroups, /proc, /sys).

Every number Glass Lens shows comes from here, and every function says where it reads
from, so you can check it yourself in a terminal.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time

CG = "/sys/fs/cgroup"
NCPU = os.cpu_count() or 1
USER_HZ = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
UID = os.getuid()

# Category colours (shared with the UI)
CATEGORIES = {
    "app":     ("Your apps", "#6aa8ff"),
    "desktop": ("Desktop", "#c38bff"),
    "system":  ("System services", "#5fe3a1"),
    "kernel":  ("Linux kernel", "#ffd479"),
    "cache":   ("File cache", "#8a90aa"),
    "free":    ("Free", "#ffffff"),
}


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def read_int(path, default=0):
    v = read(path)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def human_bytes(n, digits=1):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.{digits}f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_rate(n):
    return human_bytes(n) + "/s"


# ------------------------------------------------------------------ explanations
_EXPLAIN = None


def explanations():
    global _EXPLAIN
    if _EXPLAIN is None:
        try:
            with open("/usr/share/glassos/services.json") as f:
                _EXPLAIN = json.load(f)
        except (OSError, ValueError):
            _EXPLAIN = {}
    return _EXPLAIN


def explain(unit):
    ex = explanations()
    if unit in ex:
        return ex[unit]
    base = re.sub(r"@.*(\.\w+)$", r"@\1", unit)  # getty@tty1.service -> getty@.service
    if base in ex:
        return ex[base]
    stem = unit.rsplit(".", 1)[0]
    return ex.get(stem, "")


# ------------------------------------------------------------------ app names
_desktop_names = None
_plain = set()


def app_display_name(exe):
    """Map an executable name to the friendly name in its .desktop file."""
    global _desktop_names
    if _desktop_names is None:
        _desktop_names = {}
        for d in ("/usr/share/applications", "/usr/local/share/applications",
                  os.path.expanduser("~/.local/share/applications")):
            for f in glob.glob(os.path.join(d, "*.desktop")):
                name = execname = None
                plain = False
                try:
                    for line in open(f, errors="replace"):
                        if line.startswith("[") and name:
                            break
                        if line.startswith("Name=") and name is None:
                            name = line[5:].strip()
                        elif line.startswith("Exec=") and execname is None:
                            parts = line[5:].split()
                            if parts:
                                execname = os.path.basename(parts[0] if parts[0] != "env" else parts[-1])
                                # "glass-lens" names the app; "glass-lens --page sounds" is a shortcut into it
                                plain = all(p.startswith("%") for p in parts[1:])
                except OSError:
                    continue
                if name and execname and (plain or execname not in _desktop_names):
                    if plain or execname not in _plain:
                        _desktop_names[execname] = name
                    if plain:
                        _plain.add(execname)
    return _desktop_names.get(exe, exe)


# ------------------------------------------------------------------ CPU
class CpuSampler:
    """Reads /proc/stat (time each core spent busy vs idle since boot)."""

    def __init__(self):
        self.prev = None
        self.prev_t = None

    @staticmethod
    def _read():
        rows = {}
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("cpu"):
                    p = line.split()
                    vals = list(map(int, p[1:9]))
                    idle = vals[3] + vals[4]
                    rows[p[0]] = (sum(vals), idle)
        return rows

    def sample(self):
        now = self._read()
        t = time.monotonic()
        res = {"total": 0.0, "cores": [], "busy_us": 0.0, "interval": 0.0}
        if self.prev:
            def pct(k):
                tot = now[k][0] - self.prev[k][0]
                idl = now[k][1] - self.prev[k][1]
                return 0.0 if tot <= 0 else max(0.0, min(100.0, 100.0 * (tot - idl) / tot))
            res["total"] = pct("cpu")
            res["cores"] = [pct(k) for k in sorted((k for k in now if k != "cpu"), key=lambda s: int(s[3:]))]
            busy_j = (now["cpu"][0] - now["cpu"][1]) - (self.prev["cpu"][0] - self.prev["cpu"][1])
            res["busy_us"] = busy_j * 1e6 / USER_HZ
            res["interval"] = t - self.prev_t
        self.prev, self.prev_t = now, t
        return res


# ------------------------------------------------------------------ memory
def meminfo():
    """Reads /proc/meminfo (values in bytes)."""
    m = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            m[k] = int(v.split()[0]) * 1024
    return m


# ------------------------------------------------------------------ cgroups (who uses what)
def classify(path):
    """Turn a cgroup path into (category, unit, display name)."""
    parts = path.strip("/").split("/")
    leaf = parts[-1]
    if path == "/init.scope":
        return "system", "init.scope", "systemd (service manager)"
    if parts[0] == "system.slice":
        unit = parts[1] if len(parts) > 1 else leaf
        return "system", unit, unit.rsplit(".", 1)[0]
    if parts[0] == "user.slice":
        if leaf.startswith("session-") and leaf.endswith(".scope"):
            return "desktop", leaf, "Hyprland (window compositor)"
        if "app.slice" in parts:
            m = re.match(r"app-glass-(.+)-\d+\.scope$", leaf)
            if m:
                exe = m.group(1)
                return "app", leaf, app_display_name(exe)
            m = re.match(r"app-(?:flatpak-)?(.+?)(?:@\w+)?(?:-\d+)?\.(?:scope|service)$", leaf)
            name = m.group(1) if m else leaf
            return "app", leaf, app_display_name(name)
        if "glass-desktop.slice" in parts:
            name = leaf.rsplit(".", 1)[0].replace("glass-", "")
            name = re.sub(r"-\d+$", "", name)
            return "desktop", leaf, name.replace("-", " ").capitalize()
        if leaf.startswith("user@"):
            return "desktop", leaf, "Your user service manager"
        unit = leaf
        return "desktop", unit, unit.rsplit(".", 1)[0]
    if parts[0] == "machine.slice":
        return "app", leaf, leaf
    return "system", leaf, leaf


def _unit_cgroups():
    """Walk /sys/fs/cgroup and yield the cgroups that belong to one service/app."""
    out = []

    def walk(rel, depth):
        full = CG + rel
        try:
            entries = os.listdir(full)
        except OSError:
            return
        for e in entries:
            p = os.path.join(full, e)
            if not os.path.isdir(p):
                continue
            r = rel + "/" + e
            if e.endswith(".service") or e.endswith(".scope"):
                if e.startswith("user@") and e.endswith(".service"):
                    walk(r, depth + 1)  # descend into the user's own service tree
                    continue
                out.append(r)
            elif e.endswith(".slice") and depth < 8:
                walk(r, depth + 1)

    walk("", 0)
    return out


def _io_bytes(path):
    rb = wb = 0
    txt = read(path + "/io.stat", "")
    for line in txt.splitlines():
        for tok in line.split()[1:]:
            k, _, v = tok.partition("=")
            if k == "rbytes":
                rb += int(v)
            elif k == "wbytes":
                wb += int(v)
    return rb, wb


def _mem_split(path):
    """(memory the group really holds, reclaimable file cache) from memory.stat.
    "anon" = program data, "kernel" = kernel memory on its behalf, "shmem" = shared memory;
    "file" minus shmem is cached file data the kernel can drop any time."""
    st = {}
    for line in read(path + "/memory.stat", "").splitlines():
        k, _, v = line.partition(" ")
        if v.isdigit():
            st[k] = int(v)
    if not st:
        return read_int(path + "/memory.current", 0), 0
    used = st.get("anon", 0) + st.get("kernel", st.get("kernel_stack", 0)) + st.get("shmem", 0)
    return used, max(0, st.get("file", 0) - st.get("shmem", 0))


def _cpu_usec(path):
    for line in read(path + "/cpu.stat", "").splitlines():
        if line.startswith("usage_usec"):
            return int(line.split()[1])
    return 0


class GroupSampler:
    """Per-service/app CPU, memory and disk from cgroup v2 files (cpu.stat, memory.current, io.stat)."""

    def __init__(self):
        self.prev = {}
        self.prev_t = None
        self.prev_top = {}

    def sample(self):
        t = time.monotonic()
        dt = (t - self.prev_t) if self.prev_t else None
        groups = []
        for rel in _unit_cgroups():
            full = CG + rel
            cpu = _cpu_usec(full)
            mem, cache = _mem_split(full)
            rb, wb = _io_bytes(full)
            procs = [int(p) for p in read(full + "/cgroup.procs", "").split() if p.isdigit()]
            if not procs and mem == 0:
                continue
            cat, unit, name = classify(rel)
            g = {"path": rel, "category": cat, "unit": unit, "name": name, "mem": mem, "cache": cache,
                 "pids": procs, "cpu_pct": 0.0, "read_rate": 0.0, "write_rate": 0.0,
                 "explain": explain(unit)}
            if dt and rel in self.prev:
                pc, pr, pw = self.prev[rel]
                g["cpu_pct"] = max(0.0, (cpu - pc) / (dt * 1e6 * NCPU) * 100)
                g["read_rate"] = max(0.0, (rb - pr) / dt)
                g["write_rate"] = max(0.0, (wb - pw) / dt)
            self.prev[rel] = (cpu, rb, wb)
            groups.append(g)

        # CPU used by top-level cgroups, to work out what the kernel itself used
        top = {}
        for e in os.listdir(CG):
            p = os.path.join(CG, e)
            if os.path.isdir(p):
                top[e] = _cpu_usec(p)
        top_delta = 0.0
        if dt:
            for k, v in top.items():
                if k in self.prev_top:
                    top_delta += max(0, v - self.prev_top[k])
        self.prev_top = top
        self.prev_t = t
        return groups, top_delta, dt


# ------------------------------------------------------------------ processes
def processes(pids):
    out = []
    for pid in pids[:60]:
        st = read(f"/proc/{pid}/stat")
        if not st:
            continue
        comm = st[st.find("(") + 1: st.rfind(")")]
        rest = st[st.rfind(")") + 2:].split()
        statm = read(f"/proc/{pid}/statm", "0 0").split()
        rss = int(statm[1]) * os.sysconf("SC_PAGE_SIZE") if len(statm) > 1 else 0
        cmd = read(f"/proc/{pid}/cmdline", "").replace("\x00", " ").strip() or f"[{comm}]"
        try:
            user = os.stat(f"/proc/{pid}").st_uid
        except OSError:
            user = -1
        out.append({"pid": pid, "comm": comm, "rss": rss, "cmd": cmd, "uid": user,
                    "threads": int(rest[17]) if len(rest) > 17 else 1})
    return out


def kernel_threads():
    """Processes with no cgroup other than the root are kernel threads (kworkers etc.)."""
    procs = read(CG + "/cgroup.procs", "").split()
    return len(procs)


# ------------------------------------------------------------------ disks
class DiskSampler:
    """Reads /proc/diskstats (sectors read/written per physical disk)."""

    def __init__(self):
        self.prev = None
        self.prev_t = None

    def sample(self):
        now = {}
        with open("/proc/diskstats") as f:
            for line in f:
                p = line.split()
                name = p[2]
                if re.match(r"^(loop|ram|zram|dm-|sr|fd)", name):
                    continue
                if not os.path.exists(f"/sys/block/{name}"):
                    continue  # partitions
                now[name] = (int(p[5]) * 512, int(p[9]) * 512)
        t = time.monotonic()
        res = {}
        for k, (r, w) in now.items():
            rr = wr = 0.0
            if self.prev and k in self.prev:
                dt = t - self.prev_t
                rr = (r - self.prev[k][0]) / dt
                wr = (w - self.prev[k][1]) / dt
            res[k] = (max(0, rr), max(0, wr))
        self.prev, self.prev_t = now, t
        return res


def disks():
    out = []
    for d in sorted(os.listdir("/sys/block")):
        if re.match(r"^(loop|ram|zram|dm-|fd)", d):
            continue
        size = read_int(f"/sys/block/{d}/size") * 512
        if size == 0:
            continue
        model = read(f"/sys/block/{d}/device/model", "") or read(f"/sys/block/{d}/device/name", "")
        rot = read(f"/sys/block/{d}/queue/rotational", "0") == "1"
        rem = read(f"/sys/block/{d}/removable", "0") == "1"
        kind = "CD/DVD" if d.startswith("sr") else ("Hard disk" if rot else ("Removable" if rem else "SSD"))
        if d.startswith("nvme"):
            kind = "NVMe SSD"
        if d.startswith("vd"):
            kind = "Virtual disk"
        out.append({"name": d, "size": size, "model": model.strip(), "kind": kind})
    return out


def mounts():
    out = []
    seen = set()
    with open("/proc/mounts") as f:
        for line in f:
            dev, mnt, fs = line.split()[:3]
            if fs in ("proc", "sysfs", "devtmpfs", "devpts", "cgroup2", "securityfs", "pstore", "bpf",
                      "tracefs", "debugfs", "configfs", "fusectl", "mqueue", "hugetlbfs", "efivarfs",
                      "binfmt_misc", "autofs", "ramfs", "nsfs", "rpc_pipefs"):
                continue
            if fs == "tmpfs" and mnt not in ("/run/live/overlay",):
                continue
            if mnt.startswith("/run/user") or mnt.startswith("/snap"):
                continue
            try:
                u = shutil.disk_usage(mnt)
            except OSError:
                continue
            key = (u.total, u.used)
            if key in seen or u.total == 0:
                continue
            seen.add(key)
            label = {"/": "System", "/run/live/medium": "Live USB/DVD", "/run/live/overlay": "Live changes (RAM)",
                     "/boot/efi": "EFI boot partition", "/home": "Home"}.get(mnt, mnt)
            out.append({"mount": mnt, "label": label, "fs": fs, "total": u.total, "used": u.used, "free": u.free})
    return out


# ------------------------------------------------------------------ network
class NetSampler:
    """Reads /proc/net/dev (bytes in/out per network interface)."""

    def __init__(self):
        self.prev = None
        self.prev_t = None

    def sample(self):
        now = {}
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                name, data = line.split(":", 1)
                name = name.strip()
                if name == "lo":
                    continue
                v = data.split()
                now[name] = (int(v[0]), int(v[8]))
        t = time.monotonic()
        res = {}
        for k, (rx, tx) in now.items():
            rr = tr = 0.0
            if self.prev and k in self.prev:
                dt = t - self.prev_t
                rr = (rx - self.prev[k][0]) / dt
                tr = (tx - self.prev[k][1]) / dt
            res[k] = {"rx_rate": max(0, rr), "tx_rate": max(0, tr), "rx_total": rx, "tx_total": tx,
                      "addr": iface_addr(k), "kind": iface_kind(k)}
        self.prev, self.prev_t = now, t
        return res


def iface_kind(name):
    if os.path.isdir(f"/sys/class/net/{name}/wireless"):
        return "Wi-Fi"
    if os.path.exists(f"/sys/class/net/{name}/device"):
        return "Ethernet"
    return "Virtual"


def iface_addr(name):
    try:
        out = subprocess.run(["ip", "-o", "-4", "addr", "show", name], capture_output=True, text=True,
                             timeout=1).stdout
        m = re.search(r"inet (\S+)", out)
        return m.group(1) if m else ""
    except Exception:
        return ""


_SUDO_OK = None


def _can_sudo():
    global _SUDO_OK
    if _SUDO_OK is None:
        try:
            _SUDO_OK = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=2).returncode == 0
        except Exception:
            _SUDO_OK = False
    return _SUDO_OK


PORTS = {53: "DNS", 80: "HTTP", 443: "HTTPS", 123: "Time sync (NTP)", 22: "SSH", 67: "DHCP", 68: "DHCP",
         546: "DHCPv6", 547: "DHCPv6", 5353: "mDNS", 853: "DNS over TLS", 993: "IMAPS", 587: "SMTP",
         465: "SMTPS", 3478: "STUN", 5222: "XMPP", 1900: "SSDP"}


def connections():
    """Every open network connection, from `ss` (uses sudo -n if allowed, to name system processes)."""
    cmd = ["ss", "-H", "-tunap"]
    if UID != 0 and _can_sudo():
        cmd = ["sudo", "-n"] + cmd
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return [], []
    conns, listening = [], []
    for line in out.splitlines():
        p = line.split()
        if len(p) < 6:
            continue
        proto, state, local, peer = p[0], p[1], p[4], p[5]
        proc = ""
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        if m:
            proc = f"{m.group(1)}"
            pid = int(m.group(2))
        else:
            pid = None
        lhost, _, lport = local.rpartition(":")
        rhost, _, rport = peer.rpartition(":")
        entry = {"proto": proto, "state": state, "local": local, "peer": peer, "process": proc or "(system)",
                 "pid": pid, "lport": lport, "rport": rport, "rhost": rhost.strip("[]"),
                 "lhost": lhost.strip("[]")}
        if state in ("LISTEN", "UNCONN") and rhost in ("*", "0.0.0.0", "[::]", "::"):
            loopback = entry["lhost"].startswith("127.") or entry["lhost"] in ("::1", "localhost")
            entry["exposed"] = not loopback
            listening.append(entry)
        elif state not in ("LISTEN", "UNCONN"):
            try:
                entry["service"] = PORTS.get(int(rport), "")
            except ValueError:
                entry["service"] = ""
            conns.append(entry)
    return conns, listening


def ip_accounting():
    """Network bytes per system service since boot (systemd IPAccounting, BPF-based)."""
    try:
        units = subprocess.run(["systemctl", "list-units", "--type=service,slice,scope", "--state=active",
                                "--no-legend", "--plain"], capture_output=True, text=True, timeout=3).stdout
        names = [ln.split()[0] for ln in units.splitlines() if ln.strip()]
        if not names:
            return {}
        out = subprocess.run(["systemctl", "show", "-p", "Id,Description,IPIngressBytes,IPEgressBytes"] + names,
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return {}
    res = {}
    for block in out.strip().split("\n\n"):
        d = dict(ln.split("=", 1) for ln in block.splitlines() if "=" in ln)
        try:
            i, e = int(d.get("IPIngressBytes", "")), int(d.get("IPEgressBytes", ""))
        except ValueError:
            continue
        if i == 18446744073709551615 or e == 18446744073709551615:
            continue
        if i or e:
            res[d.get("Id", "?")] = {"in": i, "out": e, "desc": d.get("Description", "")}
    return res


def firewall_status():
    try:
        active = subprocess.run(["systemctl", "is-active", "nftables"], capture_output=True, text=True,
                                timeout=2).stdout.strip()
    except Exception:
        active = "unknown"
    return active == "active"


# ------------------------------------------------------------------ hardware
def cpu_info():
    info = {"model": "", "cores": NCPU, "arch": os.uname().machine, "max_mhz": None}
    try:
        data = json.loads(subprocess.run(["lscpu", "-J"], capture_output=True, text=True, timeout=2).stdout)
        for item in data.get("lscpu", []):
            f, v = item.get("field", "").rstrip(":"), item.get("data", "")
            if v in ("-", ""):
                continue
            if f == "Model name" and not info["model"]:
                info["model"] = v
            elif f == "CPU max MHz":
                info["max_mhz"] = v
            elif f == "Vendor ID" and not info["model"]:
                info["vendor"] = v
            for ch in item.get("children", []) or []:
                if ch.get("field", "").rstrip(":") == "Model name" and not info["model"] and ch.get("data", "-") != "-":
                    info["model"] = ch.get("data", "")
    except Exception:
        pass
    if not info["model"] and info.get("vendor"):
        info["model"] = f"{info['vendor']} processor"
    if not info["model"]:
        for line in open("/proc/cpuinfo"):
            if line.lower().startswith(("model name", "hardware")):
                info["model"] = line.split(":", 1)[1].strip()
                break
    return info


def core_freqs():
    out = []
    for i in range(NCPU):
        v = read_int(f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq", 0)
        out.append(v / 1000 if v else None)
    return out


def temperatures():
    out = []
    for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = read(hw + "/name", "sensor")
        for t in sorted(glob.glob(hw + "/temp*_input")):
            v = read_int(t, None)
            if v is None:
                continue
            label = read(t.replace("_input", "_label"), "") or name
            out.append({"sensor": name, "label": label, "c": v / 1000.0})
    if not out:
        for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            v = read_int(z + "/temp", None)
            if v:
                out.append({"sensor": read(z + "/type", "zone"), "label": read(z + "/type", "zone"), "c": v / 1000})
    return out


_gpu_names = {}


def gpus():
    out = []
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]")):
        dev = os.path.realpath(card + "/device")
        slot = os.path.basename(dev)
        driver = os.path.basename(os.path.realpath(card + "/device/driver")) if os.path.exists(card + "/device/driver") else "?"
        if slot not in _gpu_names:
            name = ""
            if re.match(r"^[0-9a-f]{4}:", slot):
                try:
                    r = subprocess.run(["lspci", "-mm", "-s", slot], capture_output=True, text=True, timeout=2).stdout
                    q = re.findall(r'"([^"]*)"', r)
                    if len(q) >= 3:
                        name = f"{q[1]} {q[2]}"
                except Exception:
                    pass
            _gpu_names[slot] = name or driver
        busy = read(card + "/device/gpu_busy_percent")
        vram_used = read_int(card + "/device/mem_info_vram_used", 0)
        vram_total = read_int(card + "/device/mem_info_vram_total", 0)
        out.append({"card": os.path.basename(card), "name": _gpu_names[slot], "driver": driver,
                    "busy": int(busy) if busy and busy.isdigit() else None,
                    "vram_used": vram_used, "vram_total": vram_total})
    return out


def batteries():
    out = []
    for ps in glob.glob("/sys/class/power_supply/*"):
        if read(ps + "/type") != "Battery" or read(ps + "/scope", "System") == "Device":
            continue
        power = read_int(ps + "/power_now", 0) / 1e6
        if not power:
            power = read_int(ps + "/current_now", 0) * read_int(ps + "/voltage_now", 0) / 1e12
        full = read_int(ps + "/energy_full", 0) or read_int(ps + "/charge_full", 0)
        design = read_int(ps + "/energy_full_design", 0) or read_int(ps + "/charge_full_design", 0)
        out.append({"name": os.path.basename(ps), "capacity": read_int(ps + "/capacity", 0),
                    "status": read(ps + "/status", ""), "watts": power,
                    "health": (full / design * 100) if design else None})
    return out


def system_summary():
    u = os.uname()
    boot = "UEFI" if os.path.isdir("/sys/firmware/efi") else "BIOS (legacy)"
    live = os.path.isdir("/run/live/medium")
    up = float(read("/proc/uptime", "0").split()[0])
    os_rel = {}
    for line in read("/etc/os-release", "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            os_rel[k] = v.strip('"')
    build = {}
    for line in read("/usr/share/glassos/build-info", "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            build[k] = v
    hypr = ""
    try:
        hypr = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "hyprland"], capture_output=True,
                              text=True, timeout=2).stdout.split("+")[0]
    except Exception:
        pass
    product = (read("/sys/class/dmi/id/sys_vendor", "") + " " + read("/sys/class/dmi/id/product_name", "")).strip()
    if not product:
        product = read("/proc/device-tree/model", "").strip("\x00")
    debian = read("/etc/debian_version", "")
    return {"kernel": u.release, "arch": u.machine, "host": u.nodename, "boot": boot, "live": live,
            "uptime": up, "os": os_rel.get("PRETTY_NAME", "GlassOS"), "build": build, "hyprland": hypr,
            "product": product, "debian": debian}


def package_stats():
    try:
        out = subprocess.run(["dpkg-query", "-W", "-f=${Installed-Size}\\n"], capture_output=True,
                             text=True, timeout=5).stdout.split()
        return len(out), sum(int(x) for x in out if x.isdigit()) * 1024
    except Exception:
        return 0, 0


def manifest():
    """The annotated list of packages GlassOS chose (/usr/share/glassos/packages.list)."""
    sections = []
    cur = None
    try:
        for line in open("/usr/share/glassos/packages.list"):
            line = line.rstrip("\n")
            if line.startswith("## "):
                cur = (line[3:].strip(), [])
                sections.append(cur)
            elif line and not line.startswith("#") and cur:
                pkg, _, why = line.partition("#")
                name = pkg.split()[0]
                tags = re.findall(r"\[(\w+)\]", pkg)
                if any(t in ("amd64", "arm64") and t != _dpkg_arch() for t in tags):
                    continue
                cur[1].append((name, why.strip()))
    except OSError:
        pass
    return sections


_ARCH = None


def _dpkg_arch():
    global _ARCH
    if _ARCH is None:
        try:
            _ARCH = subprocess.run(["dpkg", "--print-architecture"], capture_output=True, text=True,
                                   timeout=2).stdout.strip()
        except Exception:
            _ARCH = ""
    return _ARCH


def timers():
    """Scheduled jobs (systemd timers): things that run on their own, and when."""
    res = []
    for scope in ([], ["--user"]):
        try:
            out = subprocess.run(["systemctl", *scope, "list-timers", "--all", "--no-legend", "--plain",
                                  "--output=json"], capture_output=True, text=True, timeout=3).stdout
            for t in json.loads(out or "[]"):
                unit = t.get("unit", "")
                res.append({"unit": unit, "activates": t.get("activates", ""),
                            "next": t.get("next"), "user": bool(scope), "explain": explain(unit)})
        except Exception:
            continue
    return res
