#!/usr/bin/env python3
"""Run a shell command inside a headless test VM over its serial console (logs in as the live user).

  vmsh.py <arch> 'command'          prints the command's output
  vmsh.py <arch> --put LOCAL REMOTE copy a small file into the VM (base64 over serial)
"""
import base64
import os
import re
import socket
import sys
import time
import uuid

USER = os.environ.get("VMSH_USER", "glass")          # the live user; set these for an installed system
PASSWORD = os.environ.get("VMSH_PASSWORD", "glass")


class Serial:
    def __init__(self, arch):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.connect(f"out/vm/serial-{arch}.sock")
        self.s.settimeout(0.2)
        self.buf = ""

    def read_until(self, pattern, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            m = re.search(pattern, self.buf)
            if m:
                out = self.buf[:m.end()]
                self.buf = self.buf[m.end():]
                return out, m
            try:
                chunk = self.s.recv(65536)
                if chunk:
                    self.buf += chunk.decode(errors="replace")
            except socket.timeout:
                pass
        raise TimeoutError(f"timed out waiting for {pattern!r}; got: {self.buf[-400:]!r}")

    def send(self, text):
        self.s.sendall(text.encode())

    def login(self):
        self.send("\n")
        out, m = self.read_until(r"(login: $|\$ $|# $|Password: $)", 15)
        if m.group(1).startswith("login"):
            self.send(USER + "\n")
            self.read_until(r"Password: $", 10)
            self.send(PASSWORD + "\n")
            self.read_until(r"\$ $", 20)
        elif m.group(1).startswith("Password"):
            self.send(PASSWORD + "\n")
            self.read_until(r"\$ $", 20)
        # quiet, wide, no paging, talk to the running desktop
        self.run("stty -echo cols 250 rows 60; export PAGER=cat SYSTEMD_PAGER=cat TERM=dumb "
                 "XDG_RUNTIME_DIR=/run/user/$(id -u) WAYLAND_DISPLAY=wayland-1 "
                 "HYPRLAND_INSTANCE_SIGNATURE=$(ls /run/user/$(id -u)/hypr 2>/dev/null | head -n1); PS1='$ '")

    def run(self, cmd, timeout=60):
        tag = uuid.uuid4().hex[:8]
        self.send(f"echo BEGIN{tag}; {cmd}; echo END{tag} $?\n")
        out, m = self.read_until(rf"END{tag} (\d+)", timeout)
        body = out.split(f"BEGIN{tag}", 1)[-1]
        body = body[: body.rfind(f"END{tag}")]
        return body.replace("\r", "").strip("\n"), int(m.group(1))


def main():
    arch = sys.argv[1]
    ser = Serial(arch)
    ser.login()
    if sys.argv[2] == "--put":
        data = base64.b64encode(open(sys.argv[3], "rb").read()).decode()
        remote = sys.argv[4]
        ser.run(f"rm -f /tmp/.put.b64")
        for i in range(0, len(data), 3000):
            ser.run(f"printf %s '{data[i:i+3000]}' >> /tmp/.put.b64")
        out, code = ser.run(f"mkdir -p \"$(dirname '{remote}')\" && base64 -d /tmp/.put.b64 > '{remote}' && rm /tmp/.put.b64 && ls -l '{remote}'")
        print(out)
        sys.exit(code)
    out, code = ser.run(sys.argv[2], timeout=float(os.environ.get("VMSH_TIMEOUT", "90")))
    print(out)
    sys.exit(code)


if __name__ == "__main__":
    main()
