#!/usr/bin/env python3
"""Synthesise the GlassOS default sound pack.

    make-sounds.py <output-pack-dir>

These are placeholder sounds made with a tiny additive/FM synth (numpy only). They exist so
every event has *something*; the whole point is that you replace them with your own synths.
See soundpacks/README.md for the event names and how packs work.
"""
import os
import sys
import wave

import numpy as np

SR = 48000
rng = np.random.default_rng(1)
OUT = sys.argv[1] if len(sys.argv) > 1 else "soundpacks/glassos-default"

# ------------------------------------------------------------------------- primitives
NOTE = {"C": -9, "C#": -8, "Db": -8, "D": -7, "D#": -6, "Eb": -6, "E": -5, "F": -4, "F#": -3,
        "Gb": -3, "G": -2, "G#": -1, "Ab": -1, "A": 0, "A#": 1, "Bb": 1, "B": 2}


def hz(n):
    return 440.0 * 2 ** ((NOTE[n[:-1]] + (int(n[-1]) - 4) * 12) / 12)


def cents(f, c):
    return f * 2 ** (c / 1200)


def n_of(d):
    return int(round(d * SR))


def T(d):
    return np.arange(n_of(d)) / SR


def phase(f, n):
    f = np.broadcast_to(np.asarray(f, dtype=float), (n,))
    return 2 * np.pi * np.cumsum(f) / SR


def sine(f, d):
    return np.sin(phase(f, n_of(d)))


def saw(f, d, nh=48):
    n = n_of(d)
    ph = phase(f, n)
    fmax = float(np.max(f))
    out = np.zeros(n)
    for k in range(1, nh + 1):
        if k * fmax > SR * 0.42:
            break
        out += np.sin(k * ph) / k
    return out * 0.55


def tri(f, d, nh=15):
    n = n_of(d)
    ph = phase(f, n)
    out = np.zeros(n)
    for i, k in enumerate(range(1, 2 * nh, 2)):
        out += ((-1) ** i) * np.sin(k * ph) / (k * k)
    return out * 0.8


def fm(f, d, ratio=3.5, index=2.0, tau_m=0.2):
    n = n_of(d)
    t = np.arange(n) / SR
    mod = index * np.exp(-t / tau_m) * np.sin(phase(np.asarray(f) * ratio, n))
    return np.sin(phase(f, n) + mod)


def noise(d):
    return rng.standard_normal(n_of(d))


def env_exp(d, tau, attack=0.004):
    t = T(d)
    e = np.exp(-t / tau)
    if attack > 0:
        e *= np.clip(t / attack, 0, 1)
    return e


def adsr(d, a, dc, s, r):
    t = T(d)
    e = np.full_like(t, s)
    e = np.where(t < a, t / max(a, 1e-6), e)
    m = (t >= a) & (t < a + dc)
    e = np.where(m, 1 - (1 - s) * (t - a) / max(dc, 1e-6), e)
    e *= np.clip((d - t) / max(r, 1e-6), 0, 1)
    return e


def glide(f0, f1, d, shape=1.0):
    t = np.linspace(0, 1, n_of(d)) ** shape
    return f0 * (f1 / f0) ** t


# ----------------------------------------------------------------------------- filters
def _fft_filter(x, H):
    n = len(x)
    N = 1 << int(np.ceil(np.log2(max(2, n * 2))))
    X = np.fft.rfft(x, N)
    f = np.fft.rfftfreq(N, 1 / SR)
    return np.fft.irfft(X * H(f), N)[:n]


def lowpass(x, fc, order=2):
    return _fft_filter(x, lambda f: 1 / np.sqrt(1 + (f / fc) ** (2 * order)))


def highpass(x, fc, order=2):
    return _fft_filter(x, lambda f: 1 / np.sqrt(1 + (fc / np.maximum(f, 1e-3)) ** (2 * order)))


def bandpass(x, fc, q=2.0):
    return _fft_filter(x, lambda f: 1 / np.sqrt(1 + (q * (f / fc - fc / np.maximum(f, 1e-3))) ** 2))


def sweep(x, f0, f1, curve, kind="lp", steps=12, q=2.0):
    """Time-varying filter: crossfade between statically filtered copies."""
    cuts = np.geomspace(f0, f1, steps)
    if kind == "lp":
        copies = np.stack([lowpass(x, c) for c in cuts])
    else:
        copies = np.stack([bandpass(x, c, q) for c in cuts])
    pos = np.clip(curve, 0, 1) * (steps - 1)
    i = np.clip(np.floor(pos).astype(int), 0, steps - 2)
    fr = pos - i
    idx = np.arange(len(x))
    return copies[i, idx] * (1 - fr) + copies[i + 1, idx] * fr


def smoothstep(d, start=0.0, end=1.0):
    t = np.clip((T(d) - start) / max(end - start, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------------ stereo/mix
def pan(mono, p=0.0):
    a = (p + 1) * np.pi / 4
    return np.stack([mono * np.cos(a), mono * np.sin(a)])


def place(st, offset):
    pad = np.zeros((2, n_of(offset)))
    return np.concatenate([pad, st], axis=1)


def mix(*tracks):
    n = max(t.shape[1] for t in tracks)
    out = np.zeros((2, n))
    for t in tracks:
        out[:, : t.shape[1]] += t
    return out


def fftconv(a, b):
    n = len(a) + len(b) - 1
    N = 1 << int(np.ceil(np.log2(n)))
    return np.fft.irfft(np.fft.rfft(a, N) * np.fft.rfft(b, N), N)[:n]


def reverb(st, rt=1.6, wet=0.3, predelay=0.015, damp=5500):
    n_ir = n_of(rt)
    t = np.arange(n_ir) / SR
    out = []
    for ch in range(2):
        ir = rng.standard_normal(n_ir) * np.exp(-6.9 * t / rt)
        ir = lowpass(ir, damp, 1)
        ir[: n_of(predelay)] = 0
        ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
        w = fftconv(st[ch], ir)
        d = np.concatenate([st[ch], np.zeros(len(w) - st.shape[1])])
        out.append(d * (1 - wet * 0.5) + w * wet)
    return np.stack(out)


def bell(note_hz, d=1.0, tau=0.5, ratio=3.5, index=2.0, warm=0.5):
    """Glassy FM bell with a warm body partial."""
    body = fm(note_hz, d, ratio=2.0, index=1.2, tau_m=tau * 0.5) * warm
    glass = fm(note_hz, d, ratio=ratio, index=index, tau_m=tau * 0.35)
    return (body + glass) * env_exp(d, tau, 0.002)


def pad(notes, d, a=0.8, r=1.2, f0=300, f1=4000, sweep_end=None, detune=8):
    sweep_end = sweep_end or d * 0.5
    L = np.zeros(n_of(d))
    R = np.zeros(n_of(d))
    for nn in notes:
        f = hz(nn) if isinstance(nn, str) else nn
        L += saw(cents(f, -detune), d) + saw(cents(f, detune * 0.4), d)
        R += saw(cents(f, detune), d) + saw(cents(f, -detune * 0.4), d)
    curve = smoothstep(d, 0, sweep_end)
    L = sweep(L, f0, f1, curve)
    R = sweep(R, f0, f1, curve)
    e = adsr(d, a, 0.3, 0.85, r)
    return np.stack([L * e, R * e]) / max(1, len(notes))


def finish(st, peak_db=-3.0, fade_in=0.002, fade_out=0.03):
    st = st - st.mean(axis=1, keepdims=True)
    n = st.shape[1]
    fi, fo = n_of(fade_in), n_of(fade_out)
    if fi:
        st[:, :fi] *= np.linspace(0, 1, fi)
    if fo:
        st[:, -fo:] *= np.linspace(1, 0, fo)
    # trim silent tail
    mag = np.max(np.abs(st), axis=0)
    thresh = np.max(mag) * 10 ** (-60 / 20)
    last = np.nonzero(mag > thresh)[0]
    if len(last):
        st = st[:, : min(n, last[-1] + n_of(0.02))]
    return st / (np.max(np.abs(st)) + 1e-9) * 10 ** (peak_db / 20)


def write(name, st):
    os.makedirs(OUT, exist_ok=True)
    pcm = st.T * 32767 + (rng.random(st.T.shape) - rng.random(st.T.shape))  # TPDF dither
    pcm = np.clip(np.round(pcm), -32768, 32767).astype("<i2")
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"  {name:22s} {st.shape[1] / SR:5.2f}s")


# ------------------------------------------------------------------------------ sounds
def s_boot():
    d = 3.6
    chord = pad(["D2", "A2", "F#3", "C#4", "E4"], d, a=1.1, r=1.5, f0=220, f1=5200, sweep_end=1.9)
    sub = pan(sine(hz("D2"), d) * adsr(d, 0.9, 0.3, 0.8, 1.4) * 0.35)
    arp = []
    for i, nn in enumerate(["A4", "D5", "E5", "F#5", "A5", "C#6"]):
        b = bell(hz(nn), 2.0, tau=0.7, ratio=3.5, index=1.6) * 0.32
        arp.append(place(pan(b, -0.7 + i * 0.28), 0.55 + i * 0.16))
    shimmer = pan(sine(hz("A6"), d) * adsr(d, 1.6, 0.3, 0.6, 1.2) * 0.05, 0.3)
    return finish(reverb(mix(chord * 1.2, sub, shimmer, *arp), rt=3.2, wet=0.38), -2.0)


def s_login():
    notes = ["D5", "F#5", "A5", "D6"]
    parts = [place(pan(bell(hz(nn), 1.2, tau=0.45) * 0.4, -0.4 + i * 0.27), i * 0.085)
             for i, nn in enumerate(notes)]
    p = pad(["A3", "D4", "F#4"], 1.3, a=0.25, r=0.8, f0=500, f1=3000, sweep_end=0.4) * 0.7
    return finish(reverb(mix(p, *parts), rt=1.8, wet=0.32), -3.0)


def s_logout():
    notes = ["A5", "F#5", "D5", "A4"]
    parts = [place(pan(bell(hz(nn), 1.1, tau=0.4) * 0.4, 0.4 - i * 0.27), i * 0.09)
             for i, nn in enumerate(notes)]
    p = pad(["D4", "A3"], 1.2, a=0.1, r=0.9, f0=2500, f1=500, sweep_end=1.0) * 0.6
    return finish(reverb(mix(p, *parts), rt=1.6, wet=0.3), -3.5)


def s_shutdown():
    d = 2.4
    chord = pad(["D3", "A3", "E4", "F#4"], d, a=0.15, r=1.4, f0=4200, f1=260, sweep_end=2.2)
    b1 = place(pan(bell(hz("A4"), 1.6, tau=0.6) * 0.35, 0.3), 0.0)
    b2 = place(pan(bell(hz("D4"), 1.8, tau=0.7) * 0.35, -0.3), 0.22)
    return finish(reverb(mix(chord, b1, b2), rt=2.6, wet=0.36), -3.0)


def s_lock():
    d = 0.35
    thock = sine(glide(320, 120, d, 0.25), d) * env_exp(d, 0.06, 0.001)
    click = highpass(noise(0.006), 2500) * 0.25
    return finish(reverb(mix(pan(thock), pan(click)), rt=0.5, wet=0.15), -6.0)


def s_unlock():
    a = pan(bell(hz("E6"), 0.4, tau=0.08, index=1.2) * 0.5, -0.2)
    b = place(pan(bell(hz("A6"), 0.5, tau=0.12, index=1.2) * 0.5, 0.2), 0.07)
    return finish(reverb(mix(a, b), rt=0.8, wet=0.22), -6.0)


def s_notification():
    a = pan(bell(hz("A5"), 0.8, tau=0.3, index=2.2), -0.15)
    b = place(pan(bell(hz("E6"), 0.9, tau=0.38, index=2.0), 0.15), 0.11)
    return finish(reverb(mix(a * 0.8, b), rt=1.3, wet=0.25), -4.0)


def s_notification_low():
    d = 0.7
    x = (sine(hz("E6"), d) + 0.2 * sine(hz("E6") * 2, d)) * env_exp(d, 0.22)
    return finish(reverb(pan(x), rt=1.0, wet=0.25), -10.0)


def s_notification_critical():
    parts = []
    for i in range(3):
        tone = (fm(hz("E6"), 0.14, ratio=1.0, index=1.4, tau_m=0.08)
                + 0.6 * fm(hz("A5"), 0.14, ratio=2.0, index=1.0, tau_m=0.08))
        parts.append(place(pan(tone * adsr(0.14, 0.004, 0.04, 0.7, 0.05)), i * 0.17))
    tail = place(pan(bell(hz("A4"), 0.9, tau=0.35) * 0.5), 0.51)
    return finish(reverb(mix(*parts, tail), rt=1.1, wet=0.22), -3.0)


def s_error():
    d = 0.55
    body = saw(hz("D3"), d) + saw(hz("Eb3"), d) * 0.8
    body = sweep(body, 2600, 260, smoothstep(d, 0, 0.25))
    body *= env_exp(d, 0.13, 0.002)
    sub = sine(glide(hz("D3"), hz("D2"), d, 0.3), d) * env_exp(d, 0.12, 0.002) * 0.8
    return finish(reverb(mix(pan(body, -0.1), pan(sub)), rt=0.7, wet=0.18), -4.0)


def s_warning():
    a = tri(hz("E5") * (1 + 0.004 * np.sin(T(0.22) * 2 * np.pi * 6)), 0.22) * adsr(0.22, 0.01, 0.05, 0.8, 0.06)
    b = tri(hz("C5") * (1 + 0.004 * np.sin(T(0.34) * 2 * np.pi * 6)), 0.34) * adsr(0.34, 0.01, 0.05, 0.8, 0.2)
    return finish(reverb(mix(pan(a), place(pan(b), 0.2)), rt=1.0, wet=0.22), -5.0)


def _two_note(n1, n2, gap=0.08, tau=0.12, peak=-6.0, rt=0.8):
    a = pan(bell(hz(n1), 0.4, tau=tau, index=1.4) * 0.6, -0.2)
    b = place(pan(bell(hz(n2), 0.5, tau=tau * 1.3, index=1.4) * 0.6, 0.2), gap)
    return finish(reverb(mix(a, b), rt=rt, wet=0.22), peak)


def s_power(up=True):
    d = 0.45
    curve = smoothstep(d, 0, 0.3)
    if not up:
        curve = 1 - curve
    sw = sweep(noise(d), 350, 4200, curve, kind="bp", q=3.0) * env_exp(d, 0.18, 0.02) * 0.6
    tone = sine(glide(hz("D5"), hz("A5"), d, 0.5) if up else glide(hz("A5"), hz("D5"), d, 0.5), d)
    tone *= env_exp(d, 0.16, 0.01) * 0.35
    ding = place(pan(bell(hz("A6") if up else hz("D6"), 0.4, tau=0.12, index=1.0) * 0.3), 0.2)
    return finish(reverb(mix(pan(sw), pan(tone), ding), rt=0.9, wet=0.2), -6.0)


def s_battery_low():
    parts = [place(pan(tri(hz(nn), 0.24) * adsr(0.24, 0.01, 0.05, 0.75, 0.12)), i * 0.19)
             for i, nn in enumerate(["F#5", "D5", "A4"])]
    return finish(reverb(mix(*parts), rt=1.1, wet=0.24), -5.0)


def s_whoosh(f0, f1, d=0.22, peak=-14.0, pan_from=0.0, pan_to=0.0, tone=None):
    curve = smoothstep(d, 0, d * 0.8)
    x = sweep(noise(d), f0, f1, curve, kind="bp", q=2.0) * adsr(d, d * 0.35, 0.02, 0.9, d * 0.5)
    p = np.linspace(pan_from, pan_to, len(x))
    a = (p + 1) * np.pi / 4
    st = np.stack([x * np.cos(a), x * np.sin(a)])
    if tone:
        t0, t1 = tone
        st = mix(st, pan(sine(glide(t0, t1, d, 0.6), d) * env_exp(d, d * 0.4, 0.01) * 0.25))
    return finish(reverb(st, rt=0.6, wet=0.2), peak)


def s_launcher():
    d = 0.16
    pop = sine(glide(900, 1350, d, 0.15), d) * env_exp(d, 0.035, 0.001)
    return finish(pan(pop), -12.0)


def s_screenshot():
    c1 = bandpass(noise(0.03), 3200, 2.0) * env_exp(0.03, 0.008, 0.0005)
    c2 = bandpass(noise(0.05), 2200, 2.0) * env_exp(0.05, 0.014, 0.0005)
    tink = bell(hz("A6"), 0.4, tau=0.1, index=0.8) * 0.15
    return finish(reverb(mix(pan(c1, -0.2), place(pan(c2, 0.2), 0.07), place(pan(tink), 0.1)),
                         rt=0.6, wet=0.2), -6.0)


def s_volume():
    d = 0.09
    x = (sine(1000, d) + 0.3 * sine(2000, d)) * env_exp(d, 0.022, 0.001)
    return finish(pan(x), -8.0, fade_out=0.01)


SOUNDS = {
    "boot": s_boot,
    "login": s_login,
    "logout": s_logout,
    "shutdown": s_shutdown,
    "lock": s_lock,
    "unlock": s_unlock,
    "notification": s_notification,
    "notification-low": s_notification_low,
    "notification-critical": s_notification_critical,
    "error": s_error,
    "warning": s_warning,
    "device-added": lambda: _two_note("D5", "A5"),
    "device-removed": lambda: _two_note("A5", "D5"),
    "power-plugged": lambda: s_power(True),
    "power-unplugged": lambda: s_power(False),
    "battery-low": s_battery_low,
    "network-connected": lambda: _two_note("E5", "B5", gap=0.1, tau=0.16, peak=-7.0),
    "network-disconnected": lambda: _two_note("B5", "E5", gap=0.1, tau=0.16, peak=-8.0),
    "window-open": lambda: s_whoosh(700, 3200, tone=(520, 820)),
    "window-close": lambda: s_whoosh(3200, 700, tone=(820, 520)),
    "workspace": lambda: s_whoosh(600, 2400, d=0.3, pan_from=-0.6, pan_to=0.6),
    "launcher": s_launcher,
    "screenshot": s_screenshot,
    "volume": s_volume,
}

PACK_INI = """[pack]
name = GlassOS Default
author = GlassOS
description = Placeholder synth sounds generated by scripts/make-sounds.py. Replace them with your own.
version = 0.1

# Optional per-event volume (0.0 - 1.0), multiplied with your master sound volume.
[volume]
window-open = 0.7
window-close = 0.7
workspace = 0.7
"""

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    print(f"Synthesising {len(SOUNDS)} sounds into {OUT}")
    for name, fn in SOUNDS.items():
        write(name, fn())
    with open(os.path.join(OUT, "pack.ini"), "w") as f:
        f.write(PACK_INI)
