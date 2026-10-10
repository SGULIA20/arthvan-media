"""Original background music, synthesised with numpy. No samples, no copyright issues."""
import subprocess
from pathlib import Path

import numpy as np

APP_ID = {"scoremybiz": 1, "waypoint": 2}
MAJ, MIN = (0, 4, 7, 12), (0, 3, 7, 12)

# roots are semitone offsets from the key; q is chord quality per bar
MOODS = {
    "scoremybiz": {
        "mode": "major", "bpm": (104, 108, 112), "keys": (0, 2, 5, 7, 9),
        "progs": (((0, 7, 9, 5), (MAJ, MAJ, MIN, MAJ)), ((0, 9, 5, 7), (MAJ, MIN, MAJ, MAJ)),
                  ((0, 5, 9, 7), (MAJ, MAJ, MIN, MAJ)), ((9, 5, 0, 7), (MIN, MAJ, MAJ, MAJ))),
        "arp_decay": 6.0, "arp_octave": 12, "kick_every": 1, "kick_gain": 0.28, "hat_gain": 0.05,
    },
    "waypoint": {
        "mode": "minor", "bpm": (78, 82, 86), "keys": (0, 2, 3, 7, 9),
        "progs": (((0, 8, 3, 10), (MIN, MAJ, MAJ, MAJ)), ((0, 10, 8, 10), (MIN, MAJ, MAJ, MAJ)),
                  ((0, 5, 8, 7), (MIN, MIN, MAJ, MAJ)), ((0, 3, 10, 5), (MIN, MAJ, MAJ, MIN))),
        "arp_decay": 3.0, "arp_octave": 12, "kick_every": 2, "kick_gain": 0.2, "hat_gain": 0.03,
    },
}
PATTERNS = ((0, 1, 2, 3, 2, 1, 2, 3), (0, 2, 1, 3, 0, 2, 1, 3), (3, 2, 1, 0, 1, 2, 3, 2))


def _plan(app: str, seed: int):
    m = MOODS[app]
    rng = np.random.default_rng([seed, APP_ID[app]])
    bpm = m["bpm"][int(rng.integers(len(m["bpm"])))]
    key = m["keys"][int(rng.integers(len(m["keys"])))]
    prog = m["progs"][int(rng.integers(len(m["progs"])))]
    pattern = PATTERNS[int(rng.integers(len(PATTERNS)))]
    return m, rng, bpm, key, prog, pattern


def track_info(app: str, seed: int) -> dict:
    m, _, bpm, key, prog, pattern = _plan(app, seed)
    return {"bpm": bpm, "mode": m["mode"], "key": key, "roots": prog[0], "pattern": pattern}


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _add(buf: np.ndarray, start: int, seg: np.ndarray, left: float, right: float) -> None:
    end = min(len(buf), start + len(seg))
    if end <= start or start < 0:
        return
    seg = seg[: end - start]
    buf[start:end, 0] += seg * left
    buf[start:end, 1] += seg * right


def synth(app: str, seed: int, seconds: float, sr: int = 44100) -> np.ndarray:
    m, rng, bpm, key, (roots, quals), pattern = _plan(app, seed)
    n = int(round(seconds * sr))
    out = np.zeros((n, 2))
    beat = 60.0 / bpm
    bar = 4 * beat
    base = 60 + key  # C4 + key: keeps the music in the range phone speakers can play

    # pad: slow chords with a gentle second harmonic
    for b in range(int(seconds / bar) + 2):
        root, qual = roots[b % 4], quals[b % 4]
        start = int(b * bar * sr)
        length = int((bar + 0.6) * sr)
        t = np.arange(length) / sr
        env = np.minimum(1.0, t / 0.35) * np.where(t < bar, 1.0, np.exp(-(t - bar) * 7.0))
        for tone in qual[:3]:
            f = _hz(base + root + tone)
            for side, det in ((0, 0.998), (1, 1.002)):
                w = np.sin(2 * np.pi * f * det * t) + 0.5 * np.sin(2 * np.pi * 2 * f * det * t)
                seg = w * env * 0.10
                end = min(n, start + length)
                if start < n:
                    out[start:end, side] += seg[: end - start]

    # arpeggio: eighth notes on the chord tones
    step = beat / 2
    for i in range(int(seconds / step)):
        b = int(i * step // bar)
        root, qual = roots[b % 4], quals[b % 4]
        tone = qual[pattern[i % 8]]
        f = _hz(base + root + tone + m["arp_octave"])
        tl = np.arange(int(0.9 * sr)) / sr
        env = np.exp(-tl * m["arp_decay"]) * np.minimum(1.0, tl / 0.004)
        w = np.sin(2 * np.pi * f * tl) + 0.3 * np.sin(2 * np.pi * 2.01 * f * tl)
        accent = 1.0 if i % 4 == 0 else 0.7
        pan = 0.35 + 0.3 * ((i % 2))
        _add(out, int(i * step * sr), w * env * 0.11 * accent, 1 - pan, pan)

    # soft kick
    kt = np.arange(int(0.28 * sr)) / sr
    kick = np.sin(2 * np.pi * (45 * kt + (90 / 25) * (1 - np.exp(-25 * kt)))) * np.exp(-kt * 9)
    kick = kick + 0.9 * np.sin(2 * np.pi * 190 * kt) * np.exp(-kt * 38)  # mid punch so phones hear the beat
    for k in range(0, int(seconds / beat) + 1, m["kick_every"]):
        _add(out, int(k * beat * sr), kick * m["kick_gain"], 0.7, 0.7)

    # hats on the off-beats
    ht = np.arange(int(0.06 * sr)) / sr
    for k in range(int(seconds / beat)):
        noise = np.diff(rng.standard_normal(len(ht) + 1))
        pan = float(rng.uniform(0.3, 0.7))
        _add(out, int((k + 0.5) * beat * sr), noise * np.exp(-ht * 80) * m["hat_gain"], 1 - pan, pan)

    # light stereo reverb
    ir_len = int(1.0 * sr)
    irt = np.arange(ir_len) / sr
    nfft = 1 << int(np.ceil(np.log2(n + ir_len)))
    wet = np.zeros_like(out)
    for ch in (0, 1):
        ir = rng.standard_normal(ir_len) * np.exp(-irt * 4.5)
        ir /= np.sqrt(np.sum(ir ** 2))
        wet[:, ch] = np.fft.irfft(np.fft.rfft(out[:, ch], nfft) * np.fft.rfft(ir, nfft), nfft)[:n]
    out = out * 0.8 + wet * 0.35

    # fades and level
    fade_in, fade_out = int(0.4 * sr), int(1.4 * sr)
    gain = np.ones(n)
    gain[:fade_in] = np.linspace(0, 1, min(fade_in, n)) ** 2
    gain[-fade_out:] *= np.linspace(1, 0, min(fade_out, n)) ** 2
    out *= gain[:, None]
    out *= 0.85 / max(float(np.max(np.abs(out))), 1e-9)
    return out.astype(np.float32)


def write_m4a(samples: np.ndarray, path, sr: int = 44100) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", "-",
         "-c:a", "aac", "-b:a", "160k", str(path)],
        input=np.ascontiguousarray(samples, dtype="<f4").tobytes(), check=True)
