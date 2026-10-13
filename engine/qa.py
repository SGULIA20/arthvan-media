"""Quality checks on a finished Reel."""
import subprocess
from pathlib import Path

import numpy as np


def _gray_frames(path, w: int = 72, h: int = 128, fps: int = 30):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)


def blink_count(path, jump: float = 6.0) -> int:
    """Single frames much darker or brighter than BOTH neighbours: the 'blinking' a viewer sees. Normal scene changes are
    ramps, so they do not count. A good Reel scores under about 8."""
    m = _gray_frames(path).mean(axis=(1, 2))
    return sum(1 for i in range(1, len(m) - 1)
               if abs(m[i] - m[i - 1]) > jump and abs(m[i] - m[i + 1]) > jump and np.sign(m[i] - m[i - 1]) == np.sign(m[i] - m[i + 1]))


def decode_errors(path) -> int:
    """Lines of decoder complaints from decoding the whole file. A healthy Reel gives 0; a damaged one gives hundreds."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    return len([l for l in r.stderr.splitlines() if l.strip()]) + (1 if r.returncode else 0)
