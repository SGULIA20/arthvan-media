"""Missing character poses, generated from a reference picture with Gemini's image model and cut out to a transparent
PNG the story template can use. One picture costs about three rupees; nothing is generated twice.

python -m engine.poses founder_suit explaining_right     # one pose from the catalogue
python -m engine.poses --missing                           # every catalogue pose that has no PNG yet
"""
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from .config import ROOT
from .tts import api_key

MODEL = "gemini-3.1-flash-image"
CHAR_DIR = ROOT / "engine" / "assets" / "characters"
SOURCE_DIR = Path.home() / "arthvan-social" / "characters"
CATALOGUE = ROOT / "engine" / "assets" / "poses.json"
STYLE = ("Same character as the reference image: identical face, hair, skin tone, build and clothes. Pixar-style 3D render, "
         "soft studio light. Full body, head to shoes. Plain pure white background, no ground shadow, no text, no props "
         "other than those named. Portrait 9:16.")
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class PoseError(Exception):
    pass


def _generate(prompt: str, reference: bytes, key: str, model: str = MODEL) -> bytes:
    body = {"contents": [{"parts": [{"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(reference).decode()}},
                                    {"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=240, context=_CTX) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        raise PoseError(f"image model failed ({e.code}): {e.read()[:200].decode(errors='replace').replace(key, '<key>')}")
    parts = d.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    imgs = [p for p in parts if "inlineData" in p]
    if not imgs:
        raise PoseError("image model returned no picture: " + str(parts)[:200])
    return base64.b64decode(imgs[0]["inlineData"]["data"])


def cutout(bgr: np.ndarray, tol: int = 14) -> np.ndarray:
    """BGR picture on a plain background → BGRA. Background = whatever is reachable from the four corners within `tol`
    of the corner colour; enclosed light areas (a white shirt, the gap inside a tie) stay part of the character."""
    h, w = bgr.shape[:2]
    bg = np.zeros((h, w), dtype=np.uint8)
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
        cv2.floodFill(bgr.copy(), mask, seed, 0, (tol,) * 3, (tol,) * 3,
                      flags=4 | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8))
        bg |= mask[1:-1, 1:-1]
    alpha = np.where(bg > 0, 0, 255).astype(np.uint8)
    alpha = cv2.erode(alpha, np.ones((3, 3), np.uint8), iterations=1)       # trim the pale halo
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    return np.dstack([bgr, alpha])


def make_pose(character: str, pose: str, prompt: str, *, reference: Path = None, key: str = None,
              generate=_generate, out_dir: Path = CHAR_DIR, source_dir: Path = SOURCE_DIR) -> Path:
    out = Path(out_dir) / f"{character}_{pose}.png"
    if out.exists():
        return out
    key = api_key() if key is None else key
    if not key:
        raise PoseError("GEMINI_API_KEY is not set")
    reference = Path(reference) if reference else _reference(character, out_dir)
    jpg = generate(STYLE + " " + prompt, reference.read_bytes(), key)
    src = Path(source_dir) / character.split("_")[0] / f"{character}_{pose}.jpg"
    src.parent.mkdir(parents=True, exist_ok=True); src.write_bytes(jpg)
    bgr = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise PoseError("the picture could not be decoded")
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), cutout(bgr))
    return out


def _reference(character: str, out_dir: Path) -> Path:
    """The character's own full-body source picture (jpg under SOURCE_DIR), else its PNG."""
    base = character.split("_")[0]
    for name in (f"{character}_front_standing", f"{character}_front_neutral", f"{base}_front_standing", f"{base}_front_neutral"):
        for p in (SOURCE_DIR / base / f"{name}.jpg", Path(out_dir) / f"{name}.png"):
            if p.exists():
                return p
    raise PoseError(f"no reference picture for {character}")


def missing(catalogue: dict = None, out_dir: Path = CHAR_DIR) -> list:
    cat = catalogue if catalogue is not None else json.loads(CATALOGUE.read_text())
    return [(c, p, prompt) for c, poses in cat.items() for p, prompt in poses.items() if not (Path(out_dir) / f"{c}_{p}.png").exists()]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--missing"]:
        todo = missing()
        for c, p, prompt in todo:
            print(make_pose(c, p, prompt))
        print(f"{len(todo)} pose(s) made"); return 0
    if len(argv) != 2:
        print(__doc__); return 2
    cat = json.loads(CATALOGUE.read_text())
    print(make_pose(argv[0], argv[1], cat[argv[0]][argv[1]])); return 0


if __name__ == "__main__":
    sys.exit(main())
