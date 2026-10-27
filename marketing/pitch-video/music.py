"""Music bed and sound effects for the 40-second Lighty pitch: soft, instrumental, no vocals, no samples.

Everything is synthesised with numpy (felt-piano arpeggio, warm pad, sub bass, room reverb, and the effects), so the
track is royalty-free and identical on every run. 120 bpm, every scene boundary falls on a beat.

  0:00    Bm7, pad and a few piano notes, a little lower than the rest (the problem)
  0:04.5  lift into D (add9): brighter pad, arpeggio and bass come in   ← rises at the Lighty reveal
  0:08    G maj7 · Em7 under the regions map · 0:15 Bm7 · G maj7 under the churn list
  0:23.5  D for the next step · 0:27.5 G maj7 · Em7 for Ask Lighty
  0:32    Asus4 → 0:33.5 A: tension while Lighty's answer is on screen
  0:35    resolves to D, a few last notes, rings out to 0:40                ← resolves on the closing line

Sound effects come from the video itself: lighty-pitch.html lists them (soundCues), render.cjs writes that list to a
JSON file and passes it here. Kinds: click (mouse), key / space / enter (keyboard), whoosh, swish, send, shimmer,
chime, pop, tick, drop.

Usage: python3 music.py out.wav [sound-cues.json]   (prints loudness and section levels as JSON)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import wave
from collections import Counter

import numpy as np

SR = 48_000
DUR = 40.0
N = int(SR * DUR)
BEAT = 0.5
TARGET_LUFS = -16.0
CEILING_DBFS = -1.5
rng = np.random.default_rng(20261027)

PITCH = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def hz(note: str) -> float:
    m = 12 * (int(note[-1]) + 1) + PITCH[note[:-1]]
    return 440.0 * 2 ** ((m - 69) / 12)


# (start, end, pad voicing, bass, arpeggio tones)
CHORDS = [
    (0.0, 4.5, ["F#3", "A3", "B3", "D4"], None, None),                        # Bm7
    (4.5, 8.0, ["F#3", "A3", "D4", "E4"], "D2", ["D4", "F#4", "A4", "E5"]),    # Dadd9
    (8.0, 11.5, ["F#3", "G3", "B3", "D4"], "G2", ["D4", "G4", "B4", "D5"]),    # Gmaj7
    (11.5, 15.0, ["E3", "G3", "B3", "D4"], "E2", ["E4", "G4", "B4", "D5"]),   # Em7
    (15.0, 18.5, ["F#3", "A3", "B3", "D4"], "B1", ["B3", "D4", "F#4", "A4"]),  # Bm7
    (18.5, 23.5, ["F#3", "G3", "B3", "D4"], "G2", ["D4", "G4", "B4", "D5"]),  # Gmaj7
    (23.5, 27.5, ["F#3", "A3", "D4", "E4"], "D2", ["D4", "F#4", "A4", "E5"]),  # Dadd9
    (27.5, 30.5, ["F#3", "G3", "B3", "D4"], "G2", ["D4", "G4", "B4", "D5"]),  # Gmaj7
    (30.5, 32.0, ["E3", "G3", "B3", "D4"], "E2", ["E4", "G4", "B4", "D5"]),   # Em7
    (32.0, 33.5, ["E3", "A3", "B3", "D4"], "A1", ["A3", "D4", "E4", "A4"]),   # Asus4
    (33.5, 35.0, ["E3", "A3", "B3", "C#4"], "A1", ["A3", "C#4", "E4", "A4"]),  # A
    (35.0, 40.0, ["F#3", "A3", "D4", "E4"], "D2", None),                      # Dadd9, resolution
]
RESOLVE = 35.0

t_all = np.arange(N) / SR


def smooth(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def lowpass(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
    """Zero-phase Butterworth-shaped low-pass in the frequency domain (whole signal at once)."""
    f = np.fft.rfftfreq(x.shape[-1], 1 / SR)
    return np.fft.irfft(np.fft.rfft(x) / np.sqrt(1 + (f / cutoff) ** (2 * order)), n=x.shape[-1])


def highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    return x - lowpass(x, cutoff, 2)


def bandpass(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return highpass(lowpass(x, hi), lo)


def automation(points: list[tuple[float, float]]) -> np.ndarray:
    ts, vs = zip(*points)
    return np.interp(t_all, ts, vs)


# ---------------------------------------------------------------- pad
def pad() -> np.ndarray:
    out = np.zeros((2, N))
    for start, end, notes, _, _ in CHORDS:
        a0 = max(0.0, start - 0.15)
        attack = 1.1 if start == 0 else 0.6
        release = 0.9
        stop = min(DUR, end + release)
        i0, i1 = int(a0 * SR), int(stop * SR)
        t = t_all[i0:i1]
        env = smooth((t - a0) / attack)
        if end < DUR:
            env *= 1 - smooth((t - (end - 0.1)) / release)
        for note in notes:
            f0 = hz(note)
            for cents, (gl, gr) in ((-7, (0.8, 0.2)), (0, (0.5, 0.5)), (7, (0.2, 0.8))):
                f = f0 * 2 ** (cents / 1200)
                v = np.zeros_like(t)
                for h in range(1, 9):
                    v += np.sin(2 * np.pi * f * h * t + rng.uniform(0, 2 * np.pi)) / h * np.exp(-(h - 1) / 2.2)
                v *= env
                out[0, i0:i1] += gl * v
                out[1, i0:i1] += gr * v
    out *= 1 + 0.05 * np.sin(2 * np.pi * 0.17 * t_all)          # slow breathing
    dark = np.stack([lowpass(c, 700) for c in out])
    bright = np.stack([lowpass(c, 2400) for c in out])
    open_up = automation([(0, 0), (3.5, 0), (4.5, 0.65), (34.5, 0.65), (35.5, 0.45), (DUR, 0.4)])
    return dark * (1 - open_up) + bright * open_up


# ---------------------------------------------------------------- felt piano
def piano_note(freq: float, vel: float, ring: float) -> np.ndarray:
    n = int(ring * SR)
    t = np.arange(n) / SR
    y = np.zeros(n)
    partials = [1.0, 0.42, 0.2, 0.11, 0.06, 0.035, 0.02]
    for detune in (1.0, 1.0007):
        for h, amp in enumerate(partials, 1):
            fh = freq * detune * h * np.sqrt(1 + 0.00012 * h * h)
            if fh > 8000:
                break
            tau = 1.7 / (1 + 0.6 * (h - 1)) * (220 / freq) ** 0.3
            bright = vel ** (0.6 * (h - 1))                        # soft notes are darker
            y += amp * bright * np.sin(2 * np.pi * fh * t + rng.uniform(0, 2 * np.pi)) * np.exp(-t / tau)
    y *= 1 - np.exp(-t / 0.005)                                   # felt hammer: no click
    y *= np.clip((ring - t) / 0.25, 0, 1)                         # damper
    return 0.5 * vel * y


def piano() -> np.ndarray:
    out = np.zeros((2, N))

    def put(note: str, at: float, vel: float, ring: float = 2.6, pan: float = 0.0):
        y = piano_note(hz(note), vel, min(ring, DUR - at))
        i = int(at * SR)
        out[0, i:i + len(y)] += y * (0.5 - pan / 2)
        out[1, i:i + len(y)] += y * (0.5 + pan / 2)

    # the problem: sparse
    for k, note in enumerate(["B2", "F#3", "A3", "D4"]):
        put(note, 0.05 + 0.07 * k, 0.42, 3.8)
    put("F#4", 2.0, 0.3, 2.0, 0.2)
    put("A4", 3.0, 0.24, 1.2, 0.25)
    put("B3", 4.0, 0.22, 1.0, -0.15)

    # 0:04.5 – 0:35 arpeggio, quarter notes, up and down
    order = [0, 1, 2, 3, 2, 1]
    for start, end, _, _, arp in CHORDS:
        if not arp:
            continue
        beats = int(round((end - start) / BEAT))
        for b in range(beats):
            at = start + b * BEAT
            if at >= RESOLVE:
                break
            vel = (0.56 if b == 0 else 0.4) + rng.uniform(-0.03, 0.03)
            pan = (-0.25, -0.08, 0.08, 0.25)[order[b % 6]]
            put(arp[order[b % 6]], at, vel, 2.2, pan)

    # 0:35 resolution: rolled D chord that rings out, then a few last soft notes
    for k, note in enumerate(["D2", "A2", "D3", "F#3", "A3", "E4"]):
        put(note, RESOLVE + 0.06 * k, (0.3, 0.36, 0.44, 0.48, 0.5, 0.48)[k], 4.5)
    for k, note in enumerate(["D5", "A4", "F#4", "E5"]):
        put(note, RESOLVE + 1.0 + 0.5 * k, 0.24 - 0.03 * k, 2.4, (-0.2, 0.1, -0.1, 0.2)[k])
    return out


# ---------------------------------------------------------------- sub bass
def bass() -> np.ndarray:
    y = np.zeros(N)
    for start, end, _, root, _ in CHORDS:
        if not root:
            continue
        stop = min(DUR, end + 0.6)
        i0, i1 = int(start * SR), int(stop * SR)
        t = t_all[i0:i1]
        env = smooth((t - start) / 0.35)
        if end < DUR:
            env *= 1 - smooth((t - end) / 0.6)
        f = hz(root)
        y[i0:i1] += env * (np.sin(2 * np.pi * f * t) + 0.18 * np.sin(4 * np.pi * f * t))
    return np.stack([y, y])


# ---------------------------------------------------------------- room
def reverb(x: np.ndarray, rt60: float = 2.3, length: float = 2.8) -> np.ndarray:
    n = int(length * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal((2, n)) * 10 ** (-3 * t / rt60)
    ir = np.stack([lowpass(c, 4500, 1) for c in ir])
    ir[:, : int(0.022 * SR)] = 0                                   # pre-delay
    ir /= np.sqrt((ir ** 2).sum(axis=1, keepdims=True))
    size = 1 << int(np.ceil(np.log2(x.shape[-1] + n)))
    wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:, :x.shape[-1]]
    return wet


# ---------------------------------------------------------------- sound effects (mono, peak 1)
def norm(y: np.ndarray) -> np.ndarray:
    return y / (np.abs(y).max() or 1)


def secs(d: float) -> np.ndarray:
    return np.arange(int(d * SR)) / SR


def noise(n: int) -> np.ndarray:
    return rng.standard_normal(n)


def fx_click() -> np.ndarray:
    """A mouse button: a bright tick on press, a lighter one on release 75 ms later."""
    def tick(f_body: float) -> np.ndarray:
        t = secs(0.03)
        top = bandpass(noise(len(t)), 1800, 7500) * np.exp(-t / 0.0022)
        body = np.sin(2 * np.pi * f_body * t) * np.exp(-t / 0.006)
        return 0.8 * norm(top) + 0.4 * body
    y = np.zeros(int(0.12 * SR))
    a, b = tick(1400), 0.5 * tick(1900)
    y[:len(a)] += a
    i = int(0.075 * SR)
    y[i:i + len(b)] += b
    return norm(y)


def fx_key(kind: str) -> np.ndarray:
    """A laptop key: the key top, a short wooden thock, the bottom-out. Space and enter are deeper and longer."""
    big = kind != "key"
    t = secs(0.1)
    top = norm(bandpass(noise(len(t)), 1500, 6500)) * np.exp(-t / 0.0035)
    f = rng.uniform(120, 140) if big else rng.uniform(175, 245)
    thock = np.sin(2 * np.pi * f * t) * np.exp(-t / (0.03 if big else 0.016))
    late = np.clip(t - 0.011, 0, None)
    bottom = norm(bandpass(noise(len(t)), 400, 2200)) * np.exp(-late / 0.008) * (t > 0.011)
    return norm(0.75 * top + 0.5 * thock + 0.35 * bottom)


def sweep(d: float, f0: float, f1: float, peak_at: float) -> np.ndarray:
    """Noise through a low-pass whose corner moves from f0 to f1: the core of a whoosh."""
    t = secs(d)
    fc = f0 * (f1 / f0) ** (t / d)
    a = np.exp(-2 * np.pi * fc / SR)
    x, y, s = noise(len(t)), np.empty(len(t)), 0.0
    for i in range(len(t)):
        s = (1 - a[i]) * x[i] + a[i] * s
        y[i] = s
    env = smooth(t / (peak_at * d)) * (1 - smooth((t - peak_at * d) / ((1 - peak_at) * d)))
    return norm(highpass(y, 140) * env)


def bell(freqs: list[float], gap: float, decay: float, index: float = 1.6) -> np.ndarray:
    t = secs(gap * len(freqs) + decay * 4)
    y = np.zeros(len(t))
    for k, f in enumerate(freqs):
        tt = t - k * gap
        on = tt >= 0
        tt = np.clip(tt, 0, None)
        y += on * np.sin(2 * np.pi * f * tt + index * np.exp(-tt / (decay * 0.4)) * np.sin(2 * np.pi * 1.41 * f * tt)) \
            * np.exp(-tt / decay) * (1 - np.exp(-tt / 0.002))
    return norm(y)


def blip(f0: float, f1: float, d: float) -> np.ndarray:
    t = secs(d)
    f = f0 * (f1 / f0) ** (t / d)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return norm(np.sin(phase) * np.exp(-t / (d / 3)) * (1 - np.exp(-t / 0.002)))


# kind: (sound, its peak in dB against the music's peak, pan). The music sits around -14 dB RMS, so taps and clicks
# peak 8–10 dB above it and stay clearly audible.
def effect(kind: str) -> tuple[np.ndarray, float, float]:
    if kind == "click":
        return fx_click(), -4, 0.1
    if kind in ("key", "space", "enter"):
        return fx_key(kind), {"key": -6, "space": -5, "enter": -4}[kind], rng.uniform(-0.12, 0.12)
    if kind == "whoosh":
        return sweep(0.6, 250, 3200, 0.7), -6, 0.0
    if kind == "swish":
        return sweep(0.28, 900, 5000, 0.6), -13, 0.15
    if kind == "send":
        return 0.7 * sweep(0.24, 600, 4500, 0.55) + 0.4 * np.pad(blip(700, 1100, 0.08), (int(0.18 * SR), 0))[:int(0.24 * SR)], -8, 0.2
    if kind == "shimmer":
        return bell([hz("D6"), hz("A6"), hz("F#6"), hz("D7")], 0.045, 0.35, 0.8), -10, 0.0
    if kind == "chime":
        return bell([hz("A5"), hz("D6")], 0.12, 0.3, 1.2), -7, 0.15
    if kind == "pop":
        return blip(1100, 480, 0.09), -8, 0.0
    if kind == "tick":
        return blip(1700, 1000, 0.05), -17, rng.uniform(-0.3, 0.3)
    if kind == "drop":
        return blip(320, 130, 0.16), -10, 0.0
    raise ValueError(f"unknown sound cue: {kind}")


def effects(cues: list[dict]) -> np.ndarray:
    out = np.zeros((2, N))
    for c in cues:
        y, db, pan = effect(c["kind"])
        y = y * 10 ** (db / 20)
        i = int(round(c["t"] * SR))
        if i >= N:
            continue
        y = y[:N - i]
        out[0, i:i + len(y)] += y * (1 - pan) / 2 * 2 ** 0.5
        out[1, i:i + len(y)] += y * (1 + pan) / 2 * 2 ** 0.5
    return out


# ---------------------------------------------------------------- loudness
def measure(path: str) -> tuple[float, float]:
    log = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", path, "-filter_complex", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    summary = log[log.rfind("Summary:"):]
    lufs = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))
    peak = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary).group(1))
    return lufs, peak


def write(path: str, x: np.ndarray) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).round().astype("<i2").T.copy()
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main(path: str, cues_path: str | None) -> None:
    cues = []
    if cues_path:
        spec = json.load(open(cues_path, encoding="utf-8"))
        if abs(spec["duration"] - DUR) > 1e-6:
            raise SystemExit(f"the video is {spec['duration']} s, the music is {DUR} s")
        cues = spec["cues"]

    p, keys, sub = pad(), piano(), bass()
    keys_n = keys / np.abs(keys).max()
    pad_n = p / np.abs(p).max()
    sub_n = sub / np.abs(sub).max()
    dry = 0.45 * pad_n + 0.9 * keys_n
    music = dry + 0.42 * reverb(0.3 * pad_n + 0.65 * keys_n) + 0.11 * sub_n * automation([(0, 0), (4.5, 0), (4.8, 1), (DUR, 1)])
    music = highpass(music, 38)

    level = automation([(0, 0.82), (3.5, 0.82), (4.5, 1.0), (RESOLVE, 1.0), (RESOLVE + 1.6, 0.92), (DUR, 0.92)])
    typing = [c["t"] for c in cues if c["kind"] in ("key", "space", "enter")]
    if typing:   # make room for the key taps
        a, b = min(typing), max(typing)
        level *= automation([(0, 1), (a - 0.4, 1), (a - 0.1, 0.8), (b + 0.2, 0.8), (b + 0.6, 1), (DUR, 1)])
    music *= level / np.abs(music).max()

    sfx = effects(cues)
    sfx = sfx + 0.18 * reverb(sfx, rt60=0.9, length=1.2)           # the same small room, so they sit in the mix
    mix = music + sfx

    tail = np.ones(N)
    fade = t_all > DUR - 1.1
    tail[fade] = np.cos(np.pi / 2 * (t_all[fade] - (DUR - 1.1)) / 1.1) ** 2   # rings out to silence at the end
    tail *= smooth(t_all / 0.03)
    mix *= tail

    mix *= 10 ** (-6 / 20) / np.abs(mix).max()
    write(path, mix)
    lufs, peak = measure(path)
    gain_db = min(TARGET_LUFS - lufs, CEILING_DBFS - peak)
    mix *= 10 ** (gain_db / 20)
    write(path, mix)
    lufs, peak = measure(path)

    def rms(a: float, b: float) -> float:
        seg = mix[:, int(a * SR):int(b * SR)]
        return round(20 * np.log10(np.sqrt((seg ** 2).mean())), 1)

    sections = [("0:00–0:04.5 the problem", 0.5, 4.5), ("0:04.5–0:08 Lighty", 4.5, 8.0),
                ("0:08–0:35 dashboard demo", 8.0, 35.0), ("0:35–0:40 closing", 35.0, 40.0)]
    print(json.dumps({"lufs": lufs, "peak_dbfs": peak, "samples": N, "seconds": N / SR,
                      "sections": [{"name": n, "rms_dbfs": rms(a, b)} for n, a, b in sections],
                      "effects": dict(Counter(c["kind"] for c in cues))}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "music.wav", sys.argv[2] if len(sys.argv) > 2 else None)
