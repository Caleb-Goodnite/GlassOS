#!/usr/bin/env python3
"""Record a headless test VM's screen as numbered frames (for boot tests and demo videos).

  vmrec.py <arch> <outdir> [fps] [seconds]   runs until then, the VM stops, or Ctrl+C
Frames are named by milliseconds since recording started (f<ms>.jpg), so real timing can be
rebuilt. QEMU writes each frame uncompressed (fast, so the guest doesn't stutter), then ffmpeg
turns it into a JPEG in the background to keep the folder small (about 0.3 MB per frame).
"""
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor


def to_jpeg(src):
    dst = src[:-4] + ".jpg"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-q:v", "2", dst])
    if r.returncode == 0:
        os.remove(src)


def main():
    arch, outdir = sys.argv[1], os.path.abspath(sys.argv[2])
    fps = float(sys.argv[3]) if len(sys.argv) > 3 else 8
    limit = float(sys.argv[4]) if len(sys.argv) > 4 else 1e9
    os.makedirs(outdir, exist_ok=True)
    sock_path = f"out/vm/mon-{arch}.sock"
    for _ in range(100):
        if os.path.exists(sock_path):
            break
        time.sleep(0.1)
    s = socket.socket(socket.AF_UNIX)
    s.connect(sock_path)
    s.settimeout(5)

    def until_prompt():
        buf = b""
        while not buf.rstrip().endswith(b"(qemu)"):
            chunk = s.recv(65536)
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    until_prompt()
    pool = ThreadPoolExecutor(max_workers=3)
    t0 = time.time()
    with open(os.path.join(outdir, "t0.txt"), "w") as f:
        f.write(f"{t0:.3f}\n")
    n = 0
    try:
        while time.time() - t0 < limit:
            start = time.time()
            ms = int((start - t0) * 1000)
            path = f"{outdir}/f{ms:08d}.ppm"
            s.sendall(f"screendump {path}\n".encode())
            until_prompt()
            if os.path.exists(path):
                pool.submit(to_jpeg, path)
                n += 1
            time.sleep(max(0.0, 1 / fps - (time.time() - start)))
    except (EOFError, BrokenPipeError, ConnectionResetError, KeyboardInterrupt, socket.timeout):
        pass
    pool.shutdown(wait=True)
    print(f"{n} frames in {time.time() - t0:.1f}s -> {outdir}")


if __name__ == "__main__":
    main()
