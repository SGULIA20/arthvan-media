"""Load app settings and content banks; validate the shape of a bank item."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODE = Path.home() / "arthvan-social" / "logs" / "production-mode.json"     # {"mode": "stories"}: founder, 19 Oct 2026: only illustrated story Reels are made and posted
TEMPLATES = ("ink", "dusk", "spark")
KINDS = ("hook", "stat", "bars", "steps", "quote")


def load_apps() -> dict:
    data = json.loads((ROOT / "content" / "apps.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def load_global() -> dict:
    return json.loads((ROOT / "content" / "apps.json").read_text())["_global"]


def load_bank(app: str) -> list:
    return json.loads((ROOT / "content" / f"{app}.json").read_text())


def _slide_problems(i: int, s: dict) -> list:
    kind = s.get("kind")
    if kind not in KINDS:
        return [f"slide {i}: unknown kind {kind!r}"]
    out = []
    if not isinstance(s.get("text"), str) or not s["text"].strip():
        out.append(f"slide {i}: text missing")
    if kind == "stat" and not s.get("value"):
        out.append(f"slide {i}: stat needs value")
    if kind == "steps" and not (2 <= len(s.get("items", [])) <= 5):
        out.append(f"slide {i}: steps needs 2 to 5 items")
    if kind == "bars":
        rows = s.get("rows", [])
        if not (2 <= len(rows) <= 4) or any(not {"label", "value", "display"} <= set(r) for r in rows):
            out.append(f"slide {i}: bars needs 2 to 4 rows with label, value, display")
    return out


def validate_item(item: dict) -> list:
    problems = []
    for key in ("id", "caption", "hashtags"):
        if not item.get(key):
            problems.append(f"{key} missing")
    if item.get("template") not in TEMPLATES:
        problems.append(f"template must be one of {TEMPLATES}")
    slides = item.get("slides")
    if not isinstance(slides, list) or not (3 <= len(slides) <= 6):
        problems.append("slides must be a list of 3 to 6")
    else:
        for i, s in enumerate(slides):
            problems.extend(_slide_problems(i, s))
    return problems


def production_mode(path: Path = MODE) -> str:
    """'stories' (illustrated story Reels and their language versions only, in production AND in the posting calendar)
    or 'all' (the older English Reels, their conversions and the graphics sets too)."""
    try:
        return json.loads(Path(path).read_text()).get("mode", "all")
    except (OSError, ValueError, AttributeError):
        return "all"
