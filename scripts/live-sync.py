#!/usr/bin/env python3
"""Live-preview overlay/ edits in a running GlassOS VM, without rebuilding the ISO.

  python scripts/live-sync.py            serve overlay/ to the VM and watch it for saves

Inside the VM, once (it installs a small background service that survives reboots):

  curl -fsS http://10.0.2.2:8765/setup | sudo sh

From then on every file you save under overlay/ is copied to the same place in the VM within
a second or two, and whatever uses it is reloaded: Hyprland reloads its config, the top bar and
notifications reload, a running dock/Lens/Settings/etc. is restarted. Files under etc/skel/ also
go into each user's home folder (that's the copy the desktop actually reads).

Rebuild the ISO for anything outside overlay/ (package list, build scripts, boot/installer).
QEMU's user networking makes this PC reachable from the VM as 10.0.2.2, so the server only
listens on 127.0.0.1.
"""
import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERLAY = os.path.join(ROOT, "overlay")
AGENT = os.path.join(ROOT, "scripts", "live-sync-agent.py")
PORT = int(os.environ.get("LIVESYNC_PORT", "8765"))
SKIP_DIRS = {"__pycache__"}
SKIP_EXT = (".pyc", ".swp", ".tmp", "~")

lock = threading.Condition()
state = {"gen": 0, "files": {}, "stats": {}, "agent": ""}


def unix_bytes(data):
    """Windows checkouts have CRLF line endings; Linux needs LF. Binary files are left alone."""
    if b"\0" in data[:8192]:
        return data
    return data.replace(b"\r\n", b"\n")


def git_modes():
    modes = {}
    try:
        out = subprocess.run(["git", "ls-files", "-s", "overlay"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
        for line in out.splitlines():
            meta, _, path = line.partition("\t")
            modes[path[len("overlay/"):]] = 0o755 if meta.split()[0] == "100755" else 0o644
    except Exception:
        pass
    return modes


def scan(modes):
    """Return {rel: (mtime, size)} for every file under overlay/."""
    out = {}
    for d, dirs, files in os.walk(OVERLAY):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            if f.endswith(SKIP_EXT):
                continue
            p = os.path.join(d, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[os.path.relpath(p, OVERLAY).replace(os.sep, "/")] = (st.st_mtime_ns, st.st_size)
    return out


def file_entry(rel, modes):
    with open(os.path.join(OVERLAY, rel), "rb") as f:
        data = unix_bytes(f.read())
    mode = modes.get(rel)
    if mode is None:
        mode = 0o755 if data.startswith(b"#!") else 0o644
    return [hashlib.sha256(data).hexdigest(), mode]


def agent_hash():
    try:
        with open(AGENT, "rb") as f:
            return hashlib.sha256(unix_bytes(f.read())).hexdigest()
    except OSError:
        return ""


def watcher():
    modes = git_modes()
    last_modes = time.time()
    while True:
        if time.time() - last_modes > 30:
            modes, last_modes = git_modes(), time.time()
        stats = scan(modes)
        ah = agent_hash()
        with lock:
            changed = [r for r in stats if state["stats"].get(r) != stats[r]]
            removed = [r for r in state["stats"] if r not in stats]
            if changed or removed or ah != state["agent"]:
                for r in changed:
                    try:
                        state["files"][r] = file_entry(r, modes)
                    except OSError:
                        stats.pop(r, None)
                for r in removed:
                    state["files"].pop(r, None)
                state["stats"], state["agent"] = stats, ah
                state["gen"] += 1
                if state["gen"] > 1:
                    names = changed[:5] + [f"(removed) {r}" for r in removed[:3]]
                    more = len(changed) + len(removed) - len(names)
                    log("saved: " + ", ".join(names) + (f" and {more} more" if more > 0 else ""))
                lock.notify_all()
        time.sleep(0.4)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


SETUP = r"""#!/bin/sh
# Installs the GlassOS live-sync agent (development only; remove with: sudo glass-livesync-remove)
set -e
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
mkdir -p /usr/local/lib/glass-livesync
curl -fsS http://10.0.2.2:%(port)d/agent.py -o /usr/local/lib/glass-livesync/agent.py
cat > /etc/systemd/system/glass-livesync.service <<'EOF'
[Unit]
Description=GlassOS live sync from the development PC (overlay/ -> this VM)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/lib/glass-livesync/agent.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
cat > /usr/local/bin/glass-livesync-remove <<'EOF'
#!/bin/sh
systemctl disable --now glass-livesync.service
rm -rf /etc/systemd/system/glass-livesync.service /usr/local/lib/glass-livesync /usr/local/bin/glass-livesync-remove
systemctl daemon-reload
echo "Live sync removed."
EOF
chmod 755 /usr/local/bin/glass-livesync-remove
systemctl daemon-reload
systemctl enable glass-livesync.service >/dev/null 2>&1
systemctl restart glass-livesync.service
echo "Live sync is on. Edits saved in overlay/ on the PC now appear here."
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/octet-stream"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/manifest":
            since = int(q.get("since", ["-1"])[0])
            wait = min(float(q.get("wait", ["0"])[0]), 60)
            with lock:
                if state["gen"] == since:
                    lock.wait_for(lambda: state["gen"] != since, timeout=wait)
                body = json.dumps({"gen": state["gen"], "agent": state["agent"], "files": state["files"]})
            self.send(200, body.encode(), "application/json")
        elif url.path.startswith("/file/"):
            rel = urllib.parse.unquote(url.path[len("/file/"):])
            path = os.path.normpath(os.path.join(OVERLAY, rel))
            if not path.startswith(OVERLAY + os.sep) or not os.path.isfile(path):
                return self.send(404, b"not found\n", "text/plain")
            with open(path, "rb") as f:
                self.send(200, unix_bytes(f.read()))
        elif url.path == "/agent.py":
            with open(AGENT, "rb") as f:
                self.send(200, unix_bytes(f.read()), "text/x-python")
        elif url.path == "/setup":
            self.send(200, (SETUP % {"port": PORT}).encode(), "text/plain")
        else:
            self.send(404, b"not found\n", "text/plain")

    def do_POST(self):
        if self.path == "/log":
            n = int(self.headers.get("Content-Length", "0"))
            for line in self.rfile.read(n).decode(errors="replace").splitlines():
                log("vm: " + line)
            self.send(204, b"")
        else:
            self.send(404, b"")


def main():
    threading.Thread(target=watcher, daemon=True).start()
    while state["gen"] == 0:
        time.sleep(0.1)
    # On Windows "reuse address" lets two servers share a port silently; fail loudly instead
    http.server.ThreadingHTTPServer.allow_reuse_address = False
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        sys.exit(f"Port {PORT} is already in use ({e}). Stop the other server, or set LIVESYNC_PORT.")
    srv.daemon_threads = True
    log(f"Watching {OVERLAY} ({len(state['files'])} files)")
    log(f"In the VM, once:  curl -fsS http://10.0.2.2:{PORT}/setup | sudo sh")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
