"""Illustrated scenes for story Reels: one picture per scene from Google's Gemini image models (about Rs 3-4 each), kept in stories/art/<story id>/.
A story file carries   "art": {"style": "...", "cast": {"name": "who they are"}, "ref": ["mira_front_neutral.png"]}   and each scene an "image" file name and an "art" line.
python -m engine.illustrate stories/<story>.json [scene numbers]     makes every missing picture (or just the listed scenes); never redraws a picture that exists
Every call is counted in ~/arthvan-social/logs/image-spend.json (conservative estimate). Pictures are cached: re-running costs nothing."""
import base64
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import tts

ROOT = Path(__file__).resolve().parent.parent
CHAR_DIR = ROOT / "engine" / "assets" / "characters"
SPEND_FILE = Path.home() / "arthvan-social" / "logs" / "image-spend.json"
MODEL = "gemini-2.5-flash-image"
INR_PER_IMAGE = {"gemini-2.5-flash-image": 4.0, "gemini-3.1-flash-image": 6.0, "gemini-3.1-flash-lite-image": 3.0, "gemini-3-pro-image": 13.0}
_CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if Path("/etc/ssl/cert.pem").exists() else ssl.create_default_context()
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class IllustrationError(Exception):
    pass


def art_dir(story_id: str, root: Path = ROOT) -> Path:
    return Path(root) / "stories" / "art" / story_id


def compose_prompt(art: dict, scene_art: str) -> str:
    """The shared style, then who is in this scene (only the cast named in it), then the scene itself."""
    low = scene_art.lower()
    who = [f"{name}: {desc}" for name, desc in (art.get("cast") or {}).items() if name.lower() in low]
    parts = [art["style"], ("Characters, keep their look exactly as described. " + " ".join(who)) if who else "", "Scene: " + scene_art,
             "Square 1:1 composition. No text, no letters, no watermark, no captions anywhere in the picture."]
    return " ".join(p for p in parts if p)


def trim_paper_border(path: Path, size: int = 1024) -> bool:
    """The model sometimes draws the picture on a pale 'paper' with a margin. Cuts that margin off and returns a square picture; True if it changed anything."""
    from PIL import Image, ImageChops
    im = Image.open(path).convert("RGB")
    corners = [im.getpixel(c) for c in ((2, 2), (im.width - 3, 2), (2, im.height - 3), (im.width - 3, im.height - 3))]
    paper = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    if min(paper) < 200 or max(max(c) - min(c) for c in zip(*corners)) > 25:          # the corners are not one pale colour: no paper margin
        return False
    diff = ImageChops.difference(im, Image.new("RGB", im.size, paper)).convert("L").point(lambda v: 255 if v > 28 else 0)
    box = diff.getbbox()
    if not box or (box[2] - box[0]) * (box[3] - box[1]) > 0.985 * im.width * im.height:
        return False
    x0, y0, x1, y1 = box; m = int(0.03 * im.width)                                      # a little extra to lose the rounded corners
    im = im.crop((x0 + m, y0 + m, x1 - m, y1 - m))
    side = min(im.size); l, t = (im.width - side) // 2, (im.height - side) // 2
    im.crop((l, t, l + side, t + side)).resize((size, size), Image.LANCZOS).save(path)
    return True


def record_spend(model: str, path: Path = SPEND_FILE) -> float:
    d = json.loads(path.read_text()) if path.exists() else {"inr": 0.0, "images": 0, "by_model": {}}
    d["inr"] = round(d["inr"] + INR_PER_IMAGE.get(model, 6.0), 2); d["images"] += 1
    d["by_model"][model] = d["by_model"].get(model, 0) + 1
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(d, indent=1))
    return d["inr"]


def generate(prompt: str, out: Path, refs: list = (), model: str = MODEL, key: str = None, tries: int = 4, sleep=time.sleep) -> Path:
    """One picture into `out` (PNG). `refs` are image files that fix how a character looks."""
    key = key or tts.api_key()
    parts = [{"text": prompt}]
    for r in refs:
        parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(Path(r).read_bytes()).decode()}})
    body = json.dumps({"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "1:1"}}}).encode()
    last = ""
    for attempt in range(tries):
        req = urllib.request.Request(API.format(model=model), data=body, method="POST", headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=180, context=_CTX) as r:
                res = json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}".replace(key, "<key>")
            if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                sleep(10 * (attempt + 1)); continue
            raise IllustrationError(last) from None
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:150]}".replace(key, "<key>")
            if attempt < tries - 1:
                sleep(10 * (attempt + 1)); continue
            raise IllustrationError(last) from None
        for c in res.get("candidates", []):
            for p in (c.get("content") or {}).get("parts", []):
                blob = p.get("inlineData") or p.get("inline_data")
                if blob and blob.get("data"):
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(base64.b64decode(blob["data"]))
                    record_spend(model)
                    trim_paper_border(out)
                    return out
        last = "no picture in the reply: " + json.dumps(res)[:200]
        if attempt < tries - 1:
            sleep(5)
    raise IllustrationError(last)


def make_story_art(story: dict, only: list = None, root: Path = ROOT, model: str = MODEL, gen=generate) -> list:
    """Draws every scene of the story that has an "art" line and no picture yet. Returns the files drawn."""
    art = story["art"]
    refs = [CHAR_DIR / r for r in art.get("ref", [])]
    made = []
    for i, sc in enumerate(story["scenes"]):
        if not sc.get("art") or not sc.get("image") or (only and i not in only):
            continue
        out = art_dir(story["id"], root) / sc["image"]
        if out.exists():
            continue
        gen(compose_prompt(art, sc["art"]), out, [] if sc.get("noref") else refs, model)
        made.append(out)
    return made


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    story = json.loads(Path(args[0]).read_text())
    only = [int(x) for x in args[1:]] or None
    made = make_story_art(story, only)
    print(f"drew {len(made)} pictures; image spend so far Rs {json.loads(SPEND_FILE.read_text())['inr'] if SPEND_FILE.exists() else 0}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
