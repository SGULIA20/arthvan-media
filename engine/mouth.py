"""Build stable talking heads: align each open-mouth head to the neutral head and keep only the mouth change.

python -m engine.mouth            rebuilds <char>_head_talk_{a,b}_al.png for every character set in engine/assets/characters
"""
import sys
from pathlib import Path

import cv2
import numpy as np

CHARS = Path(__file__).resolve().parent / "assets" / "characters"


def _align(base, talk):
    gb = cv2.cvtColor(base[:, :, :3], cv2.COLOR_BGR2GRAY); gt = cv2.cvtColor(talk[:, :, :3], cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(5000)
    kb, db = orb.detectAndCompute(gb, (base[:, :, 3] > 128).astype(np.uint8) * 255)
    kt, dt = orb.detectAndCompute(gt, (talk[:, :, 3] > 128).astype(np.uint8) * 255)
    m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(dt, db), key=lambda x: x.distance)[:500]
    src = np.float32([kt[x.queryIdx].pt for x in m]); dst = np.float32([kb[x.trainIdx].pt for x in m])
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    if M is None or inl.sum() < 40:
        raise RuntimeError("could not align heads")
    return cv2.warpAffine(talk, M, (base.shape[1], base.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)


def _mouth_mask(base, warped):
    """Where the aligned open-mouth head differs most from the neutral head, inside the lower half of the face."""
    both = (base[:, :, 3] > 200) & (warped[:, :, 3] > 200)
    diff = cv2.absdiff(base[:, :, :3], warped[:, :, :3]).sum(axis=2).astype(np.float32)
    diff[~both] = 0
    ys, xs = np.where(base[:, :, 3] > 128); y0, y1 = ys.min(), ys.max(); x0, x1 = xs.min(), xs.max()
    diff[: y0 + int((y1 - y0) * 0.28)] = 0        # ignore hair and eyes
    diff[y0 + int((y1 - y0) * 0.62):] = 0         # ignore shoulders
    diff = cv2.GaussianBlur(diff, (0, 0), 12)
    y, x = np.unravel_index(int(diff.argmax()), diff.shape)
    fw = x1 - x0
    mask = np.zeros(base.shape[:2], np.uint8)
    cv2.ellipse(mask, (int(x), int(y) + int(fw * 0.01)), (int(fw * 0.16), int(fw * 0.11)), 0, 0, 360, 255, -1)
    return cv2.GaussianBlur(mask, (0, 0), 14).astype(np.float32) / 255.0, (int(x), int(y))


def build(char: str) -> list:
    base = cv2.imread(str(CHARS / f"{char}_head_neutral.png"), cv2.IMREAD_UNCHANGED)
    out = []
    for v in ("a", "b"):
        talk = cv2.imread(str(CHARS / f"{char}_head_talk_{v}.png"), cv2.IMREAD_UNCHANGED)
        warped = _align(base, talk)
        a, centre = _mouth_mask(base, warped)
        res = base.astype(np.float32).copy()
        for c in range(4):
            res[:, :, c] = base[:, :, c] * (1 - a) + warped[:, :, c] * a
        p = CHARS / f"{char}_head_talk_{v}_al.png"
        cv2.imwrite(str(p), res.astype(np.uint8)); out.append((p.name, centre))
    return out


if __name__ == "__main__":
    for char in sys.argv[1:] or ("lumi", "mira", "founder_suit"):
        print(char, build(char))
