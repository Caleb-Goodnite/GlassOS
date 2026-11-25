#!/usr/bin/env python3
"""GlassOS live-sync agent: runs inside a development VM as root (glass-livesync.service).

It long-polls scripts/live-sync.py on the PC (reachable as 10.0.2.2 through QEMU's user
networking), copies every changed overlay/ file to the same place in this system, and reloads
whatever uses it. Installed by:  curl -fsS http://10.0.2.2:8765/setup | sudo sh
Development only; never part of GlassOS itself.
"""
import hashlib
import json
import os
import pwd
import re
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HOST = os.environ.get("LIVESYNC_HOST", "http://10.0.2.2:8765")
SELF = os.path.abspath(__file__)
GLASS = "/usr/lib/glassos/"
counter = 0


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(path):
    try:
        with open(path, "rb") as f:
            return sha_bytes(f.read())
    except OSError:
        return None


def get(path, timeout=10):
    with urllib.request.urlopen(HOST + path, timeout=timeout) as r:
        return r.read()


def log(msg):
    print(msg, flush=True)
    try:
        req = urllib.request.Request(HOST + "/log", data=msg.encode(), method="POST")
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass


def write_atomic(dest, data, mode, uid=None, gid=None):
    d = os.path.dirname(dest)
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
        if uid is not None:
            # give the user any folders we had to create inside their home
            p = d
            while uid is not None and p.count("/") > 2 and os.stat(p).st_uid != uid:
                os.chown(p, uid, gid)
                p = os.path.dirname(p)
    tmp = f"{dest}.livesync-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.chmod(tmp, mode)
    if uid is not None:
        os.chown(tmp, uid, gid)
    os.replace(tmp, dest)


def users():
    """Accounts with a desktop home folder (the live user, or the ones made by the installer)."""
    out = []
    for p in pwd.getpwall():
        if 1000 <= p.pw_uid < 60000 and p.pw_dir.startswith("/home/") and os.path.isdir(p.pw_dir):
            out.append(p)
    return out


# ----------------------------------------------------------------------------- processes
def procs():
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) in (1, os.getpid()):
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
            if argv:
                yield int(pid), argv
        except OSError:
            pass


def proc_env(pid):
    with open(f"/proc/{pid}/environ", "rb") as f:
        env = {}
        for item in f.read().split(b"\0"):
            k, sep, v = item.decode(errors="replace").partition("=")
            if sep:
                env[k] = v
    return env


def proc_uid(pid):
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("Uid:"):
                return int(line.split()[1])
    return 0


def proc_cgroup(pid):
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            return f.read().strip().split("::", 1)[-1]
    except OSError:
        return ""


def session_envs():
    """{uid: env} for each user with a running Hyprland desktop (taken from a desktop process)."""
    found = {}
    for pid, argv in procs():
        try:
            uid = proc_uid(pid)
            if uid < 1000 or uid in found:
                continue
            env = proc_env(pid)
        except OSError:
            continue
        if env.get("HYPRLAND_INSTANCE_SIGNATURE") and env.get("WAYLAND_DISPLAY"):
            env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
            env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
            found[uid] = env
    return found


def as_user(uid, argv, env, wait=True, cwd=None):
    p = pwd.getpwuid(uid)
    kw = dict(env=env, user=uid, group=p.pw_gid, extra_groups=os.getgrouplist(p.pw_name, p.pw_gid),
              cwd=cwd if cwd and os.path.isdir(cwd) else p.pw_dir,
              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wait:
        return subprocess.run(argv, timeout=20, **kw).returncode
    return subprocess.Popen(argv, start_new_session=True, **kw)


def restart_process(pid, argv, done_units):
    global counter
    try:
        uid, env, cg = proc_uid(pid), proc_env(pid), proc_cgroup(pid)
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None
    unit = cg.rsplit("/", 1)[-1]
    slice_ = next((part for part in reversed(cg.split("/")) if part.endswith(".slice")), "app.slice")
    if unit in done_units:
        return None
    done_units.add(unit)
    if unit.endswith(".service"):
        if "/user@" in cg:
            as_user(uid, ["systemctl", "--user", "restart", unit], env)
        else:
            subprocess.run(["systemctl", "restart", unit], timeout=30)
        return unit
    # A scope (session piece or app): stop it, then start the same command the same way
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    for _ in range(30):
        if not os.path.exists(f"/proc/{pid}"):
            break
        time.sleep(0.1)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        time.sleep(0.2)
    if uid < 1000:
        return None   # not a desktop process; leave it stopped rather than guess how to start it
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    counter += 1
    names = []
    if unit.endswith(".scope"):
        base = unit[:-len(".scope")]
        m = re.match(r"(app-glass-.+)-\d+$", base)
        names = [f"{m.group(1)}-live{os.getpid()}x{counter}"] if m else [base, f"{base}-live{counter}"]
    for name in names:
        cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--slice={slice_}",
               f"--unit={name}", "--"] + argv
        p = as_user(uid, cmd, env, wait=False, cwd=cwd)
        time.sleep(0.8)
        if p.poll() in (None, 0):
            return name
    as_user(uid, argv, env, wait=False, cwd=cwd)
    return unit or os.path.basename(argv[-1])


# ----------------------------------------------------------------------------- reloads
def reload_for(changed):
    """Reload/restart what uses the changed files (absolute paths)."""
    notes = []
    envs = session_envs()
    skel = [c for c in changed if c.startswith("/etc/skel/")]

    def each_session(argv):
        for uid, env in envs.items():
            as_user(uid, argv, env)

    if any("/.config/hypr/" in c for c in skel):
        each_session(["hyprctl", "reload"])
        notes.append("Hyprland reloaded")
    if any("/.config/waybar/" in c for c in skel):
        for pid, argv in procs():
            if os.path.basename(argv[0]) == "waybar":
                os.kill(pid, signal.SIGUSR2)
        notes.append("top bar reloaded")
    if any("/.config/mako/" in c for c in skel):
        each_session(["makoctl", "reload"])
        notes.append("notifications reloaded")
    if any(c.startswith("/usr/share/glib-2.0/schemas/") for c in changed):
        subprocess.run(["glib-compile-schemas", "/usr/share/glib-2.0/schemas"], timeout=60)
        notes.append("settings schemas compiled")
    themes = {c.split("/")[4] for c in changed if c.startswith("/usr/share/icons/") and c.count("/") > 4}
    for t in themes:
        subprocess.run(["gtk-update-icon-cache", "-qf", f"/usr/share/icons/{t}"], timeout=60)
    if themes:
        notes.append("icon cache updated")
    if any(c.startswith("/etc/fonts/") for c in changed):
        subprocess.run(["fc-cache", "-f"], timeout=120)
    if any(re.match(r"/(etc|usr/lib)/systemd/", c) for c in changed):
        subprocess.run(["systemctl", "daemon-reload"], timeout=30)
        each_session(["systemctl", "--user", "daemon-reload"])
        notes.append("systemd reloaded (restart changed services yourself if needed)")

    # Running GlassOS programs that use a changed file
    patterns = set()
    for c in changed:
        if c.startswith(GLASS):
            rest = c[len(GLASS):]
            if "/" in rest:
                patterns.add(GLASS + rest.split("/")[0] + "/")   # dock/, lens/, apps/, greeter/
            elif c.endswith(".py"):
                patterns.update([GLASS, "/usr/bin/glass-"])        # shared module (glassui.py ...)
            else:
                patterns.add(c)
        elif c.startswith("/usr/bin/"):
            patterns.add(c)
        elif re.match(r"/etc/skel/\.config/gtk-[34]\.0/", c):
            patterns.add(GLASS)                                    # GlassOS apps' look
    if patterns:
        done = set()
        for pid, argv in list(procs()):
            line = " ".join(argv)
            if "glass-install" in line or "livesync" in line or "greeter" in line:
                continue
            if any(p in line for p in patterns):
                name = restart_process(pid, argv, done)
                if name:
                    notes.append(f"restarted {name}")
    return notes


# ----------------------------------------------------------------------------- main loop
def install(rel, data, mode):
    dest = "/" + rel
    write_atomic(dest, data, mode)
    if rel.startswith("etc/skel/"):
        sub = rel[len("etc/skel/"):]
        for p in users():
            write_atomic(os.path.join(p.pw_dir, sub), data, mode, p.pw_uid, p.pw_gid)
    return dest


def main():
    with open(SELF, "rb") as f:
        me = sha_bytes(f.read())
    applied = {}
    gen = -1
    first = True
    while True:
        try:
            wait = 0 if first else 25
            m = json.loads(get(f"/manifest?since={gen}&wait={wait}", timeout=wait + 10))
        except Exception:
            time.sleep(2)
            continue
        if m.get("agent") and m["agent"] != me:
            new = get("/agent.py")
            if sha_bytes(new) == m["agent"]:
                write_atomic(SELF, new, 0o755)
                log("agent updated, restarting it")
                sys.exit(0)   # systemd starts the new version
        gen = m["gen"]
        changed = []
        for rel, (sha, mode) in sorted(m["files"].items()):
            if applied.get(rel) == sha:
                continue
            if sha_file("/" + rel) == sha:
                applied[rel] = sha
                continue
            try:
                data = get("/file/" + urllib.parse.quote(rel))
            except Exception as e:
                log(f"couldn't fetch {rel}: {e}")
                continue
            if sha_bytes(data) != sha:
                continue   # saved again mid-transfer; the next manifest brings it
            try:
                changed.append(install(rel, data, mode))
                applied[rel] = sha
            except OSError as e:
                log(f"couldn't write /{rel}: {e}")
        if changed:
            names = ", ".join(c.replace("/usr/lib/glassos/", "").replace("/etc/skel/", "~/") for c in changed[:6])
            more = f" and {len(changed) - 6} more" if len(changed) > 6 else ""
            try:
                notes = reload_for(changed)
            except Exception as e:
                notes = [f"reload step failed: {e}"]
            log(f"updated {names}{more}" + (f" -> {'; '.join(notes)}" if notes else ""))
        elif first:
            log("connected; this VM already matches overlay/")
        first = False


if __name__ == "__main__":
    main()
