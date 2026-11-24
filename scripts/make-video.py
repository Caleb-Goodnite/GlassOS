#!/usr/bin/env python3
"""Turn recordings from vmrec.py into one demo video, with the system's own sounds.

  make-video.py <out.mp4> <rec-dir> [<rec-dir> ...]

Each rec-dir holds frames named f<milliseconds>.jpg (or .png), t0.txt (when recording started), and
optionally:
  marks.jsonl  written by vmmark.py: keep-start/keep-end, caption, speed, sound
  sounds.tsv   "<unix time>\t<audio file>" lines (e.g. from the guest's journal)
The video keeps real timing, except:
  * if there are keep marks, only those stretches are used
  * a screen that doesn't change for longer than STILL_MAX seconds is shortened
  * "speed" marks play a stretch faster
  * nearly black frames (QEMU's "Display output is not active") become plain black
Needs ffmpeg.
"""
import bisect
import json
import os
import subprocess
import sys
import tempfile

STILL_MAX = 1.2      # seconds a frozen screen may stay frozen
DIFF_STILL = 0.35    # mean grey-level change (0-255) below which two frames count as the same
DARK = 3.0           # a frame darker than this on average is shown as plain black
FPS = 30
W, H = 1920, 1080
TW, TH = 64, 36


def frames_in(d):
    fs = sorted(f for f in os.listdir(d) if f.startswith("f") and f.endswith((".jpg", ".png")))
    return [(int(f[1:-4]), os.path.abspath(os.path.join(d, f))) for f in fs]


def thumbs(frames, work):
    lst = os.path.join(work, "thumbs.txt")
    with open(lst, "w") as f:
        for _, p in frames:
            f.write(f"file '{p}'\n")
    out = subprocess.run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
                          "-vf", f"scale={TW}:{TH}:flags=area,format=gray", "-fps_mode", "passthrough",
                          "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    n = TW * TH
    return [out[i * n:(i + 1) * n] for i in range(len(out) // n)]


def diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def load_marks(d, t0):
    marks = []
    p = os.path.join(d, "marks.jsonl")
    if os.path.exists(p):
        marks = [json.loads(line) for line in open(p) if line.strip()]
        marks = [[m, k, os.path.abspath(v) if k in ("caption", "sound") and v else v] for m, k, v in marks]
    p = os.path.join(d, "sounds.tsv")
    if os.path.exists(p):
        for line in open(p):
            if "\t" in line:
                ts, f = line.rstrip("\n").split("\t", 1)
                marks.append([int((float(ts) - t0) * 1000), "sound", os.path.abspath(f)])
    marks.sort(key=lambda m: m[0])
    return marks


def segment(d, work, idx):
    frames = frames_in(d)
    t0 = float(open(os.path.join(d, "t0.txt")).read())
    marks = load_marks(d, t0)

    keeps, start = [], None
    for ms, kind, _ in marks:
        if kind == "keep-start":
            start = ms
        elif kind == "keep-end" and start is not None:
            keeps.append((start, ms))
            start = None
    if start is not None:
        keeps.append((start, frames[-1][0] + 1))
    if keeps:
        frames = [f for f in frames if any(a <= f[0] < b for a, b in keeps)]
    speeds = [(ms, float(v)) for ms, kind, v in marks if kind == "speed"]
    spd_ms = [s[0] for s in speeds]

    def speed_at(ms):
        i = bisect.bisect_right(spd_ms, ms) - 1
        return speeds[i][1] if i >= 0 else 1.0

    def window(ms):
        for k, (a, b) in enumerate(keeps):
            if a <= ms < b:
                return k
        return -1

    th = thumbs(frames, work)
    frames = frames[:len(th)]
    # QEMU draws "Display output is not active" while the kernel takes over the screen from
    # the boot loader. A real monitor shows black there, so the video does too.
    black = os.path.join(work, "black.png")
    if not os.path.exists(black):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={W}x{H}",
                        "-frames:v", "1", black], check=True)
    frames = [(ms, black if sum(t) / len(t) < DARK else p) for (ms, p), t in zip(frames, th)]
    durs, tmap, still, vt = [], [], 0.0, 0.0
    for i, (ms, _) in enumerate(frames):
        nxt = frames[i + 1][0] if i + 1 < len(frames) else ms + 500
        real = min((nxt - ms) / 1000.0, 1.0)
        if keeps and window(ms) != window(nxt):
            real = min(real, 0.15)                     # a cut between kept stretches: move on
        same = i > 0 and diff(th[i], th[i - 1]) < DIFF_STILL
        still = still + real if same else 0.0
        dur = real / speed_at(ms)
        if same and still > STILL_MAX:
            dur = max(0.0, dur - (still - STILL_MAX) / speed_at(ms))
            still = STILL_MAX
        tmap.append((ms, vt))
        durs.append(dur)
        vt += dur
    total = vt
    rec = [r for r, _ in tmap]

    def video_time(ms):
        i = bisect.bisect_right(rec, ms) - 1
        if i < 0:
            return 0.0
        rms, t = tmap[i]
        return t + min((ms - rms) / 1000.0 / speed_at(rms), durs[i])

    def in_kept(ms):
        return not keeps or any(a - 300 <= ms <= b + 300 for a, b in keeps)

    lst = os.path.join(work, f"seg{idx}.txt")
    with open(lst, "w") as f:
        for (ms, p), dur in zip(frames, durs):
            if dur > 0.0005:
                f.write(f"file '{p}'\nduration {dur:.4f}\n")
        f.write(f"file '{frames[-1][1]}'\n")

    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst]
    graph = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,"
             f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,fps={FPS},format=yuv420p[v0]")
    vl, n = "v0", 1
    caps = [(ms, v) for ms, kind, v in marks if kind == "caption"]
    for k, (ms, png) in enumerate(caps):
        a = video_time(ms)
        b = video_time(caps[k + 1][0]) if k + 1 < len(caps) else total
        if not png or not os.path.exists(png) or b - a < 0.3:
            continue
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", png]
        graph += f";[{vl}][{n}:v]overlay=0:0:enable='between(t,{a:.2f},{b - 0.04:.2f})'[v{n}]"
        vl, n = f"v{n}", n + 1
    sounds = [(video_time(ms), v) for ms, kind, v in marks
              if kind == "sound" and v and os.path.exists(v) and in_kept(ms)]
    cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
    silent = n
    n += 1
    alabels = [f"[{silent}:a]"]
    for t, path in sounds:
        cmd += ["-i", path]
        graph += (f";[{n}:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"adelay={int(t * 1000)}:all=1[a{n}]")
        alabels.append(f"[a{n}]")
        n += 1
    graph += f";{''.join(alabels)}amix=inputs={len(alabels)}:normalize=0:duration=first[aout]"
    out = os.path.join(work, f"seg{idx}.mp4")
    cmd += ["-filter_complex", graph, "-map", f"[{vl}]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total:.2f}", out]
    subprocess.run(cmd, check=True)
    print(f"  {d}: {total:.1f}s, {len(frames)} frames, {len(caps)} captions, {len(sounds)} sounds")
    return out


def main():
    dst, dirs = sys.argv[1], sys.argv[2:]
    work = tempfile.mkdtemp(prefix="glassvid-")
    segs = [segment(d, work, i) for i, d in enumerate(dirs)]
    lst = os.path.join(work, "all.txt")
    with open(lst, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", "-movflags", "+faststart", dst], check=True)
    print(f"{dst} written")


if __name__ == "__main__":
    main()
