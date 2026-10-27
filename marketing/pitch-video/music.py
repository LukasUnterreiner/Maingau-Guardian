"""Soundtrack for the 40-second Lighty pitch: an upbeat electronic product-demo track plus the sound effects.

Everything is synthesised with numpy (drums, bass, plucked chords, pad, arpeggio, risers, impacts and the effects),
so the track is royalty-free and identical on every run. No samples, no vocals.

120 bpm, bars of 2 s starting at 0:00.5. The arrangement follows the video's marks (from soundCues):

  0:00.5  intro: filtered plucks over Bm and G, hats come in, a riser and a reversed cymbal into the logo
  logo    impact; a half-time beat over D and A while the bulb lights up
  demo    from the next bar: full groove (kick, clap, hats, bass, offbeat plucks, side-chained pad), Bm G D A;
          an arpeggio joins in the second half
  typing  breakdown: no kick, clap or bass, so the key taps stay clear; the groove returns after the question
          is sent, with a riser into the slogan
  slogan  impact, then a chord hit on each of "See it", "Say it", "Sort it"
  close   impact and a final D chord that rings out to the end

Sound effects come from the video itself: lighty-pitch.html lists them (soundCues), render.cjs writes that list to a
JSON file and passes it here. Kinds: click (mouse), key / space / enter (keyboard), whoosh, swish, send, shimmer,
chime, pop, tick, drop.

Usage: python3 music.py out.wav sound-cues.json   (prints loudness and section levels as JSON)
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
BAR = 4 * BEAT
FIRST_BAR = 0.5
TARGET_LUFS = -14.0
CEILING_DBFS = -1.0
rng = np.random.default_rng(20261027)

PITCH = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def hz(note: str) -> float:
    m = 12 * (int(note[-1]) + 1) + PITCH[note[:-1]]
    return 440.0 * 2 ** ((m - 69) / 12)


# chord: bass root, plucked triad, pad voicing, arpeggio tones
CHORD = {
    "Bm": ("B1", ["B3", "D4", "F#4"], ["F#3", "A3", "B3", "D4"], ["B4", "D5", "F#5", "D5"]),
    "G": ("G1", ["B3", "D4", "G4"], ["F#3", "G3", "B3", "D4"], ["G4", "B4", "D5", "B4"]),
    "D": ("D2", ["A3", "D4", "F#4"], ["F#3", "A3", "D4", "E4"], ["A4", "D5", "F#5", "D5"]),
    "A": ("A1", ["A3", "C#4", "E4"], ["E3", "A3", "C#4", "E4"], ["A4", "C#5", "E5", "C#5"]),
}

t_all = np.arange(N) / SR


# ---------------------------------------------------------------- helpers
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


def norm(y: np.ndarray) -> np.ndarray:
    return y / (np.abs(y).max() or 1)


def secs(d: float) -> np.ndarray:
    return np.arange(int(d * SR)) / SR


def noise(n: int) -> np.ndarray:
    return rng.standard_normal(n)


def place(bus: np.ndarray, y: np.ndarray, at: float, gain: float = 1.0, pan: float = 0.0) -> None:
    """Add a mono or stereo sound to a stereo bus at a time in seconds."""
    i = int(round(at * SR))
    if i >= N or i < 0:
        return
    y = y[..., :N - i]
    if y.ndim == 1:
        bus[0, i:i + y.shape[-1]] += gain * y * (1 - pan) / 2 * 2 ** 0.5
        bus[1, i:i + y.shape[-1]] += gain * y * (1 + pan) / 2 * 2 ** 0.5
    else:
        bus[:, i:i + y.shape[-1]] += gain * y


def reverb(x: np.ndarray, rt60: float = 2.0, length: float = 2.4) -> np.ndarray:
    n = int(length * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal((2, n)) * 10 ** (-3 * t / rt60)
    ir = np.stack([lowpass(c, 4500, 1) for c in ir])
    ir[:, : int(0.02 * SR)] = 0                                    # pre-delay
    ir /= np.sqrt((ir ** 2).sum(axis=1, keepdims=True))
    size = 1 << int(np.ceil(np.log2(x.shape[-1] + n)))
    return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:, :x.shape[-1]]


# ---------------------------------------------------------------- instruments (mono, peak 1)
def kick() -> np.ndarray:
    t = secs(0.42)
    f = 46 + 125 * np.exp(-t / 0.032)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.3) * (1 - np.exp(-t / 0.0008))
    click = norm(highpass(noise(len(t)), 2500)) * np.exp(-t / 0.0025)
    return norm(body + 0.22 * click)


def clap() -> np.ndarray:
    t = secs(0.32)
    y = np.zeros(len(t))
    for k, at in enumerate((0, 0.011, 0.022, 0.033)):
        tt = np.clip(t - at, 0, None)
        y += (t >= at) * noise(len(t)) * np.exp(-tt / (0.004 if k < 3 else 0.11))
    return norm(bandpass(y, 900, 6500))


def hat(open_: bool = False) -> np.ndarray:
    t = secs(0.32 if open_ else 0.09)
    return norm(highpass(noise(len(t)), 7500) * np.exp(-t / (0.15 if open_ else 0.026)))


def saw(freq: float, t: np.ndarray, harmonics: int, tilt: float = 1.0) -> np.ndarray:
    y = np.zeros(len(t))
    phase = rng.uniform(0, 2 * np.pi)
    for h in range(1, harmonics + 1):
        if freq * h > 12000:
            break
        y += np.sin(2 * np.pi * freq * h * t + phase * h) / h ** tilt
    return y


def bass_note(note: str, d: float) -> np.ndarray:
    t = secs(d)
    f = hz(note)
    y = saw(f, t, 10, 1.2) * (1 - np.exp(-t / 0.004)) * (0.7 + 0.3 * np.exp(-t / 0.09))
    y *= np.clip((d - t) / 0.02, 0, 1)
    return norm(lowpass(y, 900))


_plucks: dict = {}


def pluck(notes: list[str], d: float = 0.6, bright: float = 1.0) -> np.ndarray:
    """A plucked synth chord: the upper harmonics die away first, like a closing filter."""
    key = (tuple(notes), d, bright)
    if key not in _plucks:
        _plucks[key] = _pluck(notes, d, bright)
    return _plucks[key]


def _pluck(notes: list[str], d: float, bright: float) -> np.ndarray:
    t = secs(d)
    y = np.zeros(len(t))
    for note in notes:
        for detune in (0.997, 1.003):
            f = hz(note) * detune
            for h in range(1, 16):
                if f * h > 12000:
                    break
                tau = 0.32 / (1 + 0.45 * (h - 1) / bright)
                y += np.sin(2 * np.pi * f * h * t + rng.uniform(0, 6.3)) / h * np.exp(-t / tau)
    y *= (1 - np.exp(-t / 0.002)) * np.clip((d - t) / 0.05, 0, 1)
    return norm(y)


def bell_note(note: str, d: float = 0.5) -> np.ndarray:
    t = secs(d)
    f = hz(note)
    y = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) + 0.12 * np.sin(2 * np.pi * 3.01 * f * t)
    return norm(y * np.exp(-t / 0.16) * (1 - np.exp(-t / 0.002)))


def riser(d: float) -> np.ndarray:
    t = secs(d)
    up = sweep(d, 300, 7000, 0.97)
    tone = np.sin(2 * np.pi * np.cumsum(300 * 4 ** (t / d)) / SR) * 0.15
    return norm(up + tone * (t / d) ** 2)


def reverse_cymbal(d: float = 1.0) -> np.ndarray:
    t = secs(d)
    return norm(highpass(noise(len(t)), 3500) * np.exp(-(d - t) / 0.35))


def impact() -> np.ndarray:
    t = secs(2.0)
    f = 40 + 90 * np.exp(-t / 0.08)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.7)
    crash = norm(highpass(noise(len(t)), 4000)) * np.exp(-t / 0.9) * 0.35
    return norm(boom + crash)


# ---------------------------------------------------------------- arrangement
def arrange(marks: dict) -> tuple[np.ndarray, list[tuple[str, float, float]]]:
    for name in ("logo", "slogan", "close"):
        if abs(((marks[name] - FIRST_BAR) / BAR) % 1) > 1e-6:
            raise SystemExit(f"{name} at {marks[name]} s is not on a bar (bars start at {FIRST_BAR} s, every {BAR} s)")
    bar = lambda s: int(round((s - FIRST_BAR) / BAR))
    logo, slogan, close = bar(marks["logo"]), bar(marks["slogan"]), bar(marks["close"])
    groove = bar(np.ceil((marks["demo"] - FIRST_BAR) / BAR) * BAR + FIRST_BAR)
    ty0, ty1 = marks["typing"]
    breakdown = {i for i in range(groove, slogan) if FIRST_BAR + i * BAR < ty1 and FIRST_BAR + (i + 1) * BAR > ty0 + 0.4}
    bars = int(np.ceil((DUR - FIRST_BAR) / BAR))

    def chord_of(i: int) -> str:
        if i < logo:
            return ["Bm", "G"][i % 2]
        if i < groove:
            return ["D", "A"][(i - logo) % 2]
        if i < slogan:
            return ["Bm", "G", "D", "A"][(i - groove) % 4]
        if i < close:
            return ["D", "G"][(i - slogan) % 2]
        return "D"

    drums = np.zeros((2, N)); low = np.zeros((2, N)); keys = np.zeros((2, N)); fx = np.zeros((2, N))
    K, C, HC, HO = kick(), clap(), hat(), hat(True)
    kicks: list[float] = []
    sections: list[tuple[str, float, float]] = []

    for i in range(bars):
        s = FIRST_BAR + i * BAR
        name = chord_of(i)
        root, triad, _, arp = CHORD[name]
        intro, half, outro = i < logo, logo <= i < groove, i >= close
        full = (groove <= i < close) and i not in breakdown
        if intro:
            if i == logo - 1:
                for b in range(8):
                    place(drums, HC, s + 0.25 + 0.25 * b, 0.07 + 0.01 * b, 0.25)
            for b in range(4):
                place(keys, lowpass(pluck(triad, 0.5, 0.6), 1400), s + 0.25 + 0.5 * b, 0.8)
        elif half:
            for at in (s, s + 1.0, s + 1.75):
                place(drums, K, at, 0.9); kicks.append(at)
            place(drums, C, s + 1.0, 0.45, 0.05)
            for b in range(8):
                place(drums, HC, s + 0.25 * 2 * b + 0.25, 0.11, 0.25)
            for b in range(8):
                place(low, bass_note(root if b % 4 != 3 else root[:-1] + str(int(root[-1]) + 1), 0.22), s + 0.25 * b, 0.45)
            for b in range(4):
                place(keys, pluck(triad, 0.5, 0.9), s + 0.25 + 0.5 * b, 0.5)
        elif full:
            for b in range(4):
                place(drums, HC, s + 0.25 + 0.5 * b, 0.13, 0.25)
                if marks["slogan"] - BEAT <= s + 0.5 * b < marks["slogan"]:
                    continue                                       # the beat before the slogan drops out
                place(drums, K, s + 0.5 * b, 1.0); kicks.append(s + 0.5 * b)
            place(drums, C, s + 0.5, 0.5, 0.05); place(drums, C, s + 1.5, 0.5, 0.05)
            place(drums, HO, s + 1.75, 0.12, -0.2)
            for b in range(8):
                note = root if b != 7 else root[:-1] + str(int(root[-1]) + 1)
                place(low, bass_note(note, 0.21), s + 0.25 * b, 0.55)
            for b in range(4):
                place(keys, pluck(triad, 0.45, 1.1), s + 0.25 + 0.5 * b, 0.5, (-0.15, 0.15)[b % 2])
            if i >= groove + 4 or i >= slogan:
                for b in range(8):
                    place(keys, bell_note(arp[b % 4], 0.45), s + 0.25 * b, 0.2, (-0.3, 0.3)[b % 2])
        elif i in breakdown:
            for b in range(4):
                place(drums, HC, s + 0.5 * b + 0.25, 0.05, 0.25)
                place(keys, lowpass(pluck(triad, 0.6, 0.7), 1600), s + 0.25 + 0.5 * b, 0.35)
        elif outro:
            place(keys, pluck(["D3", "A3", "D4", "F#4", "A4"], 3.5, 0.8), s, 0.8)
            for b, note in enumerate(["D5", "A4", "F#4", "E5", "D5"]):
                place(keys, bell_note(note, 0.7), s + 0.5 + 0.5 * b, 0.16 - 0.02 * b, (-0.3, 0.3)[b % 2])
        sections.append((name, s, s + BAR))

    # the bar before the slogan builds with a clap roll and a riser
    pre = FIRST_BAR + (slogan - 1) * BAR
    for b in range(8):
        place(drums, C, pre + 1.0 + 0.125 * b, 0.12 + 0.04 * b, 0.05)
    place(fx, riser(BAR), pre, 0.3)
    place(fx, reverse_cymbal(1.0), marks["logo"] - 1.0, 0.35)
    place(fx, riser(BAR), marks["logo"] - BAR, 0.22)
    place(fx, reverse_cymbal(1.0), marks["slogan"] - 1.0, 0.35)

    # impacts and the slogan's three hits
    for at, g in ((marks["logo"], 0.9), (marks["slogan"], 1.0), (marks["close"], 0.75)):
        place(fx, impact(), at, g)
        place(drums, K, at, 1.0); kicks.append(at)
    for k, at in enumerate(marks["hits"]):
        place(keys, pluck(CHORD[["D", "G", "D"][k]][1] + [["D5", "B4", "F#5"][k]], 0.7, 1.6), at, 0.85)
        place(drums, C, at, 0.4, 0.05)
        place(fx, impact()[: int(0.6 * SR)] * np.linspace(1, 0, int(0.6 * SR)) ** 2, at, 0.45)

    # pad under everything from the logo on, swells in during the intro
    pad = np.zeros((2, N))
    for i in range(bars):
        s = FIRST_BAR + i * BAR
        e = min(DUR, s + BAR + 0.6)
        tt = t_all[int(max(0, s - 0.1) * SR):int(e * SR)] - s
        env = smooth((tt + 0.1) / 0.4) * (1 - smooth((tt - BAR) / 0.6))
        for note in CHORD[chord_of(i)][2]:
            v = saw(hz(note) * 0.998, tt, 8, 1.3) + saw(hz(note) * 1.002, tt, 8, 1.3)
            seg = slice(int(max(0, s - 0.1) * SR), int(max(0, s - 0.1) * SR) + len(tt))
            pad[0, seg] += 0.6 * v * env; pad[1, seg] += 0.6 * v * env
    pad = np.stack([lowpass(c, 1500) for c in pad])
    pad *= automation([(0, 0.0), (0.4, 0.85), (marks["logo"], 1.0), (DUR, 1.0)])

    # side-chain: everything but the drums ducks under each kick
    duck = np.ones(N)
    for at in kicks:
        i0 = int(at * SR); n = min(int(0.4 * SR), N - i0)
        if n > 0:
            duck[i0:i0 + n] *= 1 - 0.55 * np.exp(-np.arange(n) / SR / 0.11)

    low = low * (0.6 + 0.4 * duck)
    keys_n, pad_n = keys / (np.abs(keys).max() or 1), pad / (np.abs(pad).max() or 1)
    music = (1.0 * drums / np.abs(drums).max() + 0.55 * low / np.abs(low).max()
             + (0.5 * keys_n + 0.22 * pad_n) * duck + 0.45 * fx / np.abs(fx).max())
    music += 0.22 * reverb(0.5 * keys_n + 0.3 * pad_n + 0.15 * drums / np.abs(drums).max()) * duck
    music = highpass(music, 30)
    music /= np.abs(music).max()
    music = np.tanh(1.6 * music) / np.tanh(1.6)                      # gentle limiter, a little glue
    return music, sections


# ---------------------------------------------------------------- sound effects (mono, peak 1)
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
    """Noise through a low-pass whose corner moves from f0 to f1: the core of a whoosh or a riser."""
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


# kind: (sound, its peak in dB against the music's peak, pan). Taps and clicks are mostly 2–7 kHz, where the
# music is thin, so they cut through without being loud.
def effect(kind: str) -> tuple[np.ndarray, float, float]:
    if kind == "click":
        return fx_click(), -1, 0.1
    if kind in ("key", "space", "enter"):
        return fx_key(kind), {"key": -7, "space": -6, "enter": -4}[kind], rng.uniform(-0.12, 0.12)
    if kind == "whoosh":
        return sweep(0.6, 250, 3200, 0.7), -8, 0.0
    if kind == "swish":
        return sweep(0.28, 900, 5000, 0.6), -14, 0.15
    if kind == "send":
        return 0.7 * sweep(0.24, 600, 4500, 0.55) + 0.4 * np.pad(blip(700, 1100, 0.08), (int(0.18 * SR), 0))[:int(0.24 * SR)], -8, 0.2
    if kind == "shimmer":
        return bell([hz("D6"), hz("A6"), hz("F#6"), hz("D7")], 0.045, 0.35, 0.8), -11, 0.0
    if kind == "chime":
        return bell([hz("A5"), hz("D6")], 0.12, 0.3, 1.2), -6, 0.15
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
        place(out, y, c["t"], 10 ** (db / 20), pan)
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


def main(path: str, cues_path: str) -> None:
    spec = json.load(open(cues_path, encoding="utf-8"))
    if abs(spec["duration"] - DUR) > 1e-6:
        raise SystemExit(f"the video is {spec['duration']} s, the music is {DUR} s")
    marks, cues = spec["marks"], spec["cues"]

    music, _ = arrange(marks)
    a, b = marks["typing"]
    music *= automation([(0, 1), (a - 0.3, 1), (a, 0.8), (b, 0.8), (b + 0.3, 1), (DUR, 1)])   # room for the taps

    sfx = effects(cues)
    sfx = sfx + 0.18 * reverb(sfx, rt60=0.9, length=1.2)           # the same small room, so they sit in the mix
    mix = music + sfx

    tail = np.ones(N)
    fade = t_all > DUR - 1.2
    tail[fade] = np.cos(np.pi / 2 * (t_all[fade] - (DUR - 1.2)) / 1.2) ** 2   # rings out to silence at the end
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

    m = marks
    sections = [(f"0:00–{m['logo']:g} s the problem", 0.5, m["logo"]), (f"{m['logo']:g}–{m['demo']:g} s Lighty", m["logo"], m["demo"]),
                (f"{m['demo']:g}–{m['slogan']:g} s dashboard demo", m["demo"], m["slogan"]),
                (f"{m['typing'][0]:.1f}–{m['typing'][1]:.1f} s typing (breakdown)", *m["typing"]),
                (f"{m['slogan']:g}–{m['close']:g} s slogan", m["slogan"], m["close"]), (f"{m['close']:g}–40 s closing", m["close"], DUR)]
    print(json.dumps({"lufs": lufs, "peak_dbfs": peak, "samples": N, "seconds": N / SR,
                      "sections": [{"name": n, "rms_dbfs": rms(a, b)} for n, a, b in sections],
                      "effects": dict(Counter(c["kind"] for c in cues))}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "music.wav", sys.argv[2] if len(sys.argv) > 2 else "sound-cues.json")
