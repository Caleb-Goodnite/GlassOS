#!/usr/bin/env python3
"""Drive a headless test VM through its QEMU monitor socket (used for automated boot tests).

  vmctl.py <arch> shot out.png     screenshot
  vmctl.py <arch> type "text"      type text (US layout)
  vmctl.py <arch> key ctrl-alt-f2  press a key combo (QEMU sendkey names)
  vmctl.py <arch> hmp "info status" any monitor command
  vmctl.py <arch> move X Y         glide the mouse pointer to screen pixel X,Y
  vmctl.py <arch> click X Y        glide there and left-click (add "right" for a right-click)
  vmctl.py <arch> drag X1 Y1 X2 Y2 press the left button at X1,Y1, glide to X2,Y2, release
Mouse commands use QMP (out/vm/qmp-<arch>.sock); the screen size comes from a screendump.
"""
import json
import os
import socket
import sys
import time

KEYS = {" ": "spc", "\n": "ret", "\t": "tab", "-": "minus", "=": "equal", "/": "slash", ".": "dot",
        ",": "comma", ";": "semicolon", "'": "apostrophe", "[": "bracket_left", "]": "bracket_right",
        "\\": "backslash", "`": "grave_accent"}
SHIFTED = {"_": "minus", "+": "equal", "?": "slash", ">": "dot", "<": "comma", ":": "semicolon",
           '"': "apostrophe", "{": "bracket_left", "}": "bracket_right", "|": "backslash", "~": "grave_accent",
           "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0"}


def hmp(arch, cmd, wait=0.6):
    s = socket.socket(socket.AF_UNIX)
    s.connect(f"out/vm/ctl-{arch}.sock")   # the recorder keeps mon-<arch>.sock busy
    s.settimeout(wait)
    try:
        s.recv(65536)
    except socket.timeout:
        pass
    s.sendall((cmd + "\n").encode())
    out = b""
    end = time.time() + wait
    while time.time() < end:
        try:
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
        except socket.timeout:
            break
    s.close()
    return out.decode(errors="replace")


def keyname(ch):
    if ch in KEYS:
        return KEYS[ch]
    if ch in SHIFTED:
        return "shift-" + SHIFTED[ch]
    if ch.isupper():
        return "shift-" + ch.lower()
    return ch


SCREEN = (1920, 1080)   # replaced by the real size (screen_size) before any mouse command


def screen_size(arch):
    """Read the VM's current screen size from the header of a quick screendump."""
    path = os.path.abspath(f"out/vm/size-{arch}.ppm")
    try:
        os.remove(path)
    except OSError:
        pass
    hmp(arch, f"screendump {path}", 0.5)
    for _ in range(40):
        if os.path.exists(path) and os.path.getsize(path) > 32:
            break
        time.sleep(0.05)
    with open(path, "rb") as f:
        head = f.read(32).split()
    return int(head[1]), int(head[2])
POS_FILE = "out/vm/pointer-{arch}.txt"


class QMP:
    def __init__(self, arch):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.connect(f"out/vm/qmp-{arch}.sock")
        self.f = self.s.makefile("rw")
        self.f.readline()
        self.cmd("qmp_capabilities")

    def cmd(self, name, **args):
        self.f.write(json.dumps({"execute": name, "arguments": args}) + "\n")
        self.f.flush()
        while True:
            r = json.loads(self.f.readline())
            if "return" in r or "error" in r:
                return r

    def abs(self, x, y):
        sx = int(x * 32767 / (SCREEN[0] - 1))
        sy = int(y * 32767 / (SCREEN[1] - 1))
        self.cmd("input-send-event", events=[{"type": "abs", "data": {"axis": "x", "value": sx}},
                                             {"type": "abs", "data": {"axis": "y", "value": sy}}])

    def button(self, btn, down):
        self.cmd("input-send-event", events=[{"type": "btn", "data": {"down": down, "button": btn}}])


def glide(arch, q, x, y, ms=450):
    """Move like a hand would: ease from the last position to x,y."""
    path = POS_FILE.format(arch=arch)
    try:
        x0, y0 = (float(v) for v in open(path).read().split())
    except (OSError, ValueError):
        x0, y0 = SCREEN[0] / 2, SCREEN[1] / 2
    steps = max(1, ms // 16)
    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3 - 2 * t)
        q.abs(x0 + (x - x0) * e, y0 + (y - y0) * e)
        time.sleep(0.016)
    with open(path, "w") as f:
        f.write(f"{x} {y}")


def main():
    global SCREEN
    arch, op, *rest = sys.argv[1:]
    if op == "shot":
        print(hmp(arch, f"screendump {rest[0]} -f png", 2.5).strip().splitlines()[-1:])
    elif op == "type":
        for ch in rest[0]:
            hmp(arch, f"sendkey {keyname(ch)}", 0.05)
    elif op == "key":
        hmp(arch, f"sendkey {rest[0]}", 0.2)
    elif op == "hmp":
        print(hmp(arch, rest[0], 1.5))
    elif op == "drag":
        SCREEN = screen_size(arch)
        q = QMP(arch)
        x1, y1, x2, y2 = (float(v) for v in rest[:4])
        glide(arch, q, x1, y1)
        time.sleep(0.15)
        q.button("left", True)
        time.sleep(0.15)
        glide(arch, q, x2, y2, ms=900)
        time.sleep(0.15)
        q.button("left", False)
    elif op == "scroll":
        # scroll X Y N: N wheel notches at X,Y; negative N scrolls up
        SCREEN = screen_size(arch)
        q = QMP(arch)
        glide(arch, q, float(rest[0]), float(rest[1]))
        n = int(rest[2])
        for _ in range(abs(n)):
            for down in (True, False):
                q.button("wheel-down" if n > 0 else "wheel-up", down)
            time.sleep(0.06)
    elif op in ("move", "click"):
        SCREEN = screen_size(arch)
        q = QMP(arch)
        x, y = float(rest[0]), float(rest[1])
        glide(arch, q, x, y)
        if op == "click":
            btn = rest[2] if len(rest) > 2 else "left"
            time.sleep(0.12)
            q.button(btn, True)
            time.sleep(0.08)
            q.button(btn, False)


if __name__ == "__main__":
    main()
