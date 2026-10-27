"""Music bed for the 30-second Guardian pitch: soft, instrumental, no vocals, no samples.

Everything is synthesised with numpy (felt-piano arpeggio, warm pad, sub bass, room reverb), so the track is
royalty-free and identical on every run. 120 bpm, every scene boundary falls on a beat.

  0:00  Bm7, pad and a few piano notes, a little lower than the rest
  0:04  lift into D (add9): brighter pad, arpeggio and bass come in    ← "rises slightly at the reveal"
  0:09  G maj7 · 0:14 Bm7 · 0:19 Em7 · 0:24 Asus4 → A (tension under the proof figure)
  0:27  resolves to D, arpeggio stops, chord rings out to 0:30          ← "resolves on the end card"

Usage: python3 music.py out.wav   (prints loudness and section levels as JSON)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import wave

import numpy as np

SR = 48_000
DUR = 30.0
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
    (0.0, 4.0, ["F#3", "A3", "B3", "D4"], None, None),                      # Bm7
    (4.0, 9.0, ["F#3", "A3", "D4", "E4"], "D2", ["D4", "F#4", "A4", "E5"]),  # Dadd9
    (9.0, 14.0, ["F#3", "G3", "B3", "D4"], "G2", ["D4", "G4", "B4", "D5"]),  # Gmaj7
    (14.0, 19.0, ["F#3", "A3", "B3", "D4"], "B1", ["B3", "D4", "F#4", "A4"]),  # Bm7
    (19.0, 24.0, ["E3", "G3", "B3", "D4"], "E2", ["E4", "G4", "B4", "D5"]),  # Em7
    (24.0, 25.5, ["E3", "A3", "B3", "D4"], "A1", ["A3", "D4", "E4", "A4"]),  # Asus4
    (25.5, 27.0, ["E3", "A3", "B3", "C#4"], "A1", ["A3", "C#4", "E4", "A4"]),  # A
    (27.0, 30.0, ["F#3", "A3", "D4", "E4"], "D2", None),                     # Dadd9, resolution
]

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
    open_up = automation([(0, 0), (3.0, 0), (4.0, 0.65), (26.5, 0.65), (27.5, 0.45), (30, 0.4)])
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

    # hook: sparse
    for k, note in enumerate(["B2", "F#3", "A3", "D4"]):
        put(note, 0.05 + 0.07 * k, 0.42, 3.8)
    put("F#4", 2.0, 0.3, 2.0, 0.2)
    put("A4", 3.0, 0.24, 1.2, 0.25)

    # 0:04 – 0:27 arpeggio, quarter notes, up and down
    order = [0, 1, 2, 3, 2, 1]
    for start, end, _, _, arp in CHORDS:
        if not arp:
            continue
        beats = int(round((end - start) / BEAT))
        for b in range(beats):
            at = start + b * BEAT
            if at >= 27.0:
                break
            vel = (0.56 if b == 0 else 0.4) + rng.uniform(-0.03, 0.03)
            pan = (-0.25, -0.08, 0.08, 0.25)[order[b % 6]]
            put(arp[order[b % 6]], at, vel, 2.2, pan)

    # 0:27 resolution: rolled D chord that rings out
    for k, note in enumerate(["D2", "A2", "D3", "F#3", "A3", "E4"]):
        put(note, 27.0 + 0.06 * k, (0.3, 0.36, 0.44, 0.48, 0.5, 0.48)[k], 3.0)
    put("D5", 27.5, 0.26, 2.5, 0.2)
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
    size = 1 << int(np.ceil(np.log2(N + n)))
    wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:, :N]
    return wet


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


def main(path: str) -> None:
    p, keys, sub = pad(), piano(), bass()
    keys_n = keys / np.abs(keys).max()
    pad_n = p / np.abs(p).max()
    sub_n = sub / np.abs(sub).max()
    dry = 0.45 * pad_n + 0.9 * keys_n
    mix = dry + 0.42 * reverb(0.3 * pad_n + 0.65 * keys_n) + 0.11 * sub_n * automation([(0, 0), (4, 0), (4.3, 1), (30, 1)])
    mix = highpass(mix, 38)

    level = automation([(0, 0.72), (3.0, 0.72), (4.0, 1.0), (27.0, 1.0), (28.6, 0.92), (30.0, 0.92)])
    tail = np.ones(N)
    fade = t_all > 28.9
    tail[fade] = np.cos(np.pi / 2 * (t_all[fade] - 28.9) / 1.1) ** 2  # rings out to silence at 0:30
    tail *= smooth(t_all / 0.03)
    mix *= level * tail

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

    sections = [("0:00–0:04 hook", 0.5, 4.0), ("0:04–0:09 reveal", 4.0, 9.0), ("0:09–0:24 values", 9.0, 24.0),
                ("0:24–0:27 proof", 24.0, 27.0), ("0:27–0:30 end card", 27.0, 30.0)]
    print(json.dumps({"lufs": lufs, "peak_dbfs": peak, "samples": N, "seconds": N / SR,
                      "sections": [{"name": n, "rms_dbfs": rms(a, b)} for n, a, b in sections]}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "music.wav")
