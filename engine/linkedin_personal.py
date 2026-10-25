"""LinkedIn personal lane: one short, hand-written post a day with a picture, on the founder's own profile.

The bank is content/linkedin_personal.json. Nothing generated goes out: every post is written by hand and linted here.
Usage: python -m engine.linkedin_personal [render|prepare|post] [--date YYYY-MM-DD]
  render  = draw the picture only; prepare = everything except publishing; post = publish (used by the workflow).
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import linkedin, notify
from .config import ROOT, load_global
from .linkedin import LinkedInError
from .lint import _phrase_pattern

PILLARS = ("model", "finance", "ai", "world", "founder")
LABELS = {"model": "Business model", "finance": "Finance", "ai": "AI for finance", "world": "World", "founder": "Founder notes"}
ACCENTS = {"model": "#F5B700", "finance": "#5EEAD4", "ai": "#C4B5FD", "world": "#FF9A7A", "founder": "#7DD3FC"}
CHANNEL = "linkedin_personal"
BANK = ROOT / "content" / "linkedin_personal.json"
TEMPLATE = ROOT / "engine" / "templates" / "linkedin_card.html"
SIZE = (1080, 1350)
MAX_HOOK, MAX_BODY, MAX_POST = 140, 1000, 1500     # hook: what a phone shows before "...see more" (founder, 25 Oct 2026)
DOC_WEEKDAYS = (0, 2, 4)            # Mon, Wed, Fri (Lagos): a swipeable document; other days the single picture (test from 26 Oct 2026)
MAX_TITLE, MAX_POINTS, MAX_POINT, MIN_SLIDES, MAX_SLIDES = 60, 5, 70, 2, 6
EM_DASH = "—"
_DIGIT = re.compile(r"\d")
_TAG = re.compile(r"^#[A-Za-z][A-Za-z0-9]*$")


def load_personal(root: Path = ROOT) -> dict:
    return json.loads((Path(root) / "content" / "linkedin_personal.json").read_text())


def cards(item: dict) -> list:
    return list(item["slides"]) if item.get("slides") else [item["card"]]


def deck(item: dict) -> list:
    """The pages of a document post: the opening line, the picture card, one page per point, and the question."""
    c = item["card"] if item.get("card") else cards(item)[0]
    pages = [{"title": item["hook"].strip()}, c]
    pages += [{"title": pt, "kicker": f"{LABELS[item['pillar']]} · {i + 1} of {len(c.get('points', []))}"} for i, pt in enumerate(c.get("points", []))]
    return pages + [{"title": item["question"].strip(), "kicker": "Your turn"}]


def _texts(item: dict):
    yield "hook", str(item.get("hook") or "")
    yield "body", str(item.get("body") or "")
    yield "question", str(item.get("question") or "")
    for i, c in enumerate(cards(item) if item.get("card") or item.get("slides") else []):
        yield f"card {i + 1} title", c.get("title", "")
        for p in c.get("points", []):
            yield f"card {i + 1} points", p


def _card_problems(where: str, c: dict) -> list:
    out = []
    if not c.get("title"):
        out.append(f"{where}: card needs a title")
    elif len(c["title"]) > MAX_TITLE:
        out.append(f"{where}: title longer than {MAX_TITLE} characters")
    pts = c.get("points", [])
    if len(pts) > MAX_POINTS:
        out.append(f"{where}: more than {MAX_POINTS} points")
    if any(len(p) > MAX_POINT for p in pts):
        out.append(f"{where}: a point is longer than {MAX_POINT} characters")
    return out


def lint_personal(item: dict, settings: dict) -> list:
    """A non-empty result means: do not post this item."""
    problems = []
    for k in ("id", "pillar", "hook", "body", "question", "hashtags"):
        if not item.get(k):
            problems.append(f"missing {k}")
    if item.get("pillar") not in PILLARS:
        problems.append(f"unknown pillar {item.get('pillar')!r}")
    banned = [(p, _phrase_pattern(p)) for p in settings.get("banned_phrases") or load_global()["banned_phrases"]]   # this lane: hype words only; numbers need a facts note
    posted = [(p, re.compile(re.escape(p), re.I)) for p in settings.get("already_posted", [])]   # founder, 19 Oct: never repeat a topic he posted himself
    for where, text in _texts(item):
        if EM_DASH in text:
            problems.append(f"{where}: em-dash")
        for phrase, pat in banned:
            if pat.search(text):
                problems.append(f"{where}: banned phrase {phrase.strip()!r}")
        for phrase, pat in posted:
            if pat.search(text):
                problems.append(f"{where}: already posted by the founder {phrase!r}")
        if _DIGIT.search(text) and not item.get("facts"):
            problems.append(f"{where}: number without a facts note in {text!r}")
    if len(str(item.get("hook") or "")) > MAX_HOOK:
        problems.append(f"hook longer than {MAX_HOOK} characters")
    if len(str(item.get("body") or "")) > MAX_BODY:
        problems.append(f"body longer than {MAX_BODY} characters")
    if not str(item.get("question") or "").rstrip().endswith("?"):
        problems.append("question must end with a question mark")
    tags = _tags(item, settings)
    if not settings["min_hashtags"] <= len(tags) <= settings["max_hashtags"]:
        problems.append(f"hashtags: {len(tags)} with the base tags, need {settings['min_hashtags']} to {settings['max_hashtags']}")
    if any(not _TAG.match(t) for t in tags):
        problems.append("hashtags: letters and digits only, starting with #")
    if "slides" in item:
        if not MIN_SLIDES <= len(item["slides"]) <= MAX_SLIDES:
            problems.append(f"slides: need {MIN_SLIDES} to {MAX_SLIDES} cards for a carousel")
        for i, c in enumerate(item["slides"]):
            problems += _card_problems(f"slide {i + 1}", c)
    elif item.get("card"):
        problems += _card_problems("card", item["card"])
    else:
        problems.append("missing card")
    if not problems:
        text, _ = build_text(item, settings)
        if len(text) > MAX_POST:
            problems.append(f"post longer than {MAX_POST} characters")
    return problems


def _tags(item: dict, settings: dict) -> list:
    return list(dict.fromkeys([t for t in item.get("hashtags", []) if t not in settings["base_hashtags"]] + settings["base_hashtags"]))


def build_text(item: dict, settings: dict) -> tuple:
    return "\n\n".join([item["hook"].strip(), item["body"].strip(), item["question"].strip()]), _tags(item, settings)


def alt_text(card: dict) -> str:
    pts = card.get("points", [])
    return (card["title"] + (": " + ", ".join(pts) if pts else ""))[:290]


# ---------- which item goes out ----------
def _entries(log: Path) -> list:
    out = []
    if Path(log).exists():
        for line in Path(log).read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def used_ids(log: Path) -> list:
    """Ids published on this lane, oldest use first; an id used again moves to the end."""
    order = []
    for e in _entries(log):
        if e.get("channel") == CHANNEL and e.get("status") == "published" and e.get("item"):
            if e["item"] in order:
                order.remove(e["item"])
            order.append(e["item"])
    return order


def order(items: list, log: Path) -> list:
    used = used_ids(log)
    fresh = [i for i in items if i["id"] not in used]
    old = sorted([i for i in items if i["id"] in used], key=lambda i: used.index(i["id"]))
    return fresh + old


def pick(day: date, items: list, log: Path) -> dict:
    return order(items, log)[0]


def day_status(log: Path, day: date):
    status = None
    for e in _entries(log):
        if e.get("channel") == CHANNEL and e.get("date") == day.isoformat():
            status = e.get("status")
    return status


# ---------- picture ----------
def _card_data(item: dict, c: dict, index: int, total: int) -> dict:
    return {"kicker": c.get("kicker") or LABELS[item["pillar"]], "title": c["title"], "points": c.get("points", []),
            "stat": c.get("stat", ""), "stat_label": c.get("stat_label", ""), "source": c.get("source", ""),
            "accent": ACCENTS[item["pillar"]], "index": index, "total": total, "name": "Sanjeev Gulia", "brand": "SG Learning"}


def render_cards(item: dict, out_dir: Path) -> list:
    """One 1080 x 1350 JPEG per card. Raises RuntimeError when a picture is the wrong size or blank."""
    from playwright.sync_api import sync_playwright
    from .render import verify_image
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cs = cards(item)
    paths = []
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch()
        try:
            for i, c in enumerate(cs):
                page = browser.new_page(viewport={"width": SIZE[0], "height": SIZE[1]}, device_scale_factor=1)
                page.add_init_script(f"window.CARD={json.dumps(_card_data(item, c, i + 1, len(cs)))};")
                page.goto(TEMPLATE.as_uri())
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(200)
                png = Path(tmp) / f"c{i}.png"
                page.screenshot(path=str(png))
                page.close()
                jpg = out_dir / f"card_{i + 1}.jpg"
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), "-q:v", "2", "-pix_fmt", "yuvj420p", str(jpg)], check=True)
                problems = verify_image(jpg, *SIZE)
                if problems:
                    raise RuntimeError("; ".join(problems))
                paths.append(jpg)
        finally:
            browser.close()
    return paths


# ---------- the run ----------
def _git_publish(paths: list, message: str) -> None:
    from .run_daily import git_publish
    git_publish(paths, message)


def _sync_repo() -> None:
    from .run_daily import sync_repo
    sync_repo()


@dataclass
class Deps:
    render_cards: Callable = render_cards
    post_images: Callable = linkedin.post_images
    post_document: Callable = linkedin.post_document
    make_pdf: Callable = linkedin.jpegs_to_pdf
    git_publish: Callable = _git_publish
    notify: Callable = field(default_factory=lambda: notify.send)
    sync_repo: Callable = _sync_repo
    sleep: Callable = time.sleep


PUSH_TRIES = 3


def _save_log(deps: Deps, log: Path, message: str) -> bool:
    """Commit and push the log; a push that keeps failing must not stay silent (the safety run would post again)."""
    for i in range(PUSH_TRIES):
        try:
            deps.git_publish([log], message)
            return True
        except Exception as e:                                # noqa: BLE001
            print(f"log push failed ({i + 1}/{PUSH_TRIES}): {e}")
            if i + 1 < PUSH_TRIES:
                deps.sleep(20)
    return False


def post_url(urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{urn}"


def _append(log: Path, entry: dict) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def lagos_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).date()


def run(mode: str, day: date, *, root: Path = ROOT, env=None, deps: Deps = None, bank: dict = None) -> int:
    import os
    env = os.environ if env is None else env
    deps = deps or Deps()
    root = Path(root)
    if env.get("PAUSE") == "1" or (root / "PAUSE").exists():
        print("paused: nothing to do")
        return 0
    token, urn = env.get("LINKEDIN_ACCESS_TOKEN"), env.get("LINKEDIN_PERSON_URN")
    if mode == "post" and not (token and urn):
        print("LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN must be set")
        return 1
    bank = bank or load_personal(root)
    settings, items = bank["settings"], bank["items"]
    log = root / "logs" / "posts.jsonl"
    if mode == "post":
        deps.sync_repo()
        if day_status(log, day) == "published":
            print(f"{day}: personal post already out, nothing to do")
            return 0
    item = None
    for cand in order(items, log):
        problems = lint_personal(cand, settings)
        if not problems:
            item = cand
            break
        print(f"lint rejected {cand['id']}: {problems}")
    if item is None:
        print("every item in the bank failed lint")
        if mode == "post":
            deps.notify("LinkedIn personal post: nothing went out today, every item in the bank failed lint.")
        return 1
    entry = {"date": day.isoformat(), "channel": CHANNEL, "item": item["id"]}

    def failed(what: str, e: Exception) -> int:
        print(f"{what} failed: {type(e).__name__}: {e}")
        if mode == "post":
            _append(log, dict(entry, status="failed", error=f"{what}: {type(e).__name__}: {str(e)[:250]}"))
            _save_log(deps, log, f"log: {CHANNEL} failed {day}")
            deps.notify(f"LinkedIn personal post failed today ({item['id']}), {what}: {str(e)[:200]}")
        return 1

    try:
        paths = deps.render_cards(item, root / "out" / "linkedin" / day.isoformat())
    except Exception as e:                                    # noqa: BLE001  a blank picture or a Chromium crash
        return failed("picture", e)
    text, tags = build_text(item, settings)
    alts = [alt_text(c) for c in cards(item)]
    print(f"{day} {item['id']} ({item['pillar']}): {len(paths)} picture(s)\n\n{text}\n\n{' '.join(tags)}\n")
    if mode != "post":
        return 0
    post_id, fmt = None, "picture"
    if day.weekday() in DOC_WEEKDAYS:
        try:
            pages = deps.render_cards({**item, "slides": deck(item)}, root / "out" / "linkedin" / day.isoformat() / "deck")
            pdf = deps.make_pdf(pages, root / "out" / "linkedin" / day.isoformat() / "deck.pdf")
            post_id, fmt = deps.post_document(token, urn, text, tags, pdf, item["hook"].strip()), "document"
        except Exception as e:                                # noqa: BLE001  the picture still goes out today
            print(f"document post failed, posting the picture instead: {type(e).__name__}: {e}")
    if post_id is None:
        try:
            post_id = deps.post_images(token, urn, text, tags, paths, alts)
        except Exception as e:                                # noqa: BLE001  LinkedInError, or an odd API body (KeyError)
            return failed("post", e)
    _append(log, dict(entry, status="published", id=post_id, format=fmt))
    saved = _save_log(deps, log, f"log: {CHANNEL} published {day}")
    url = post_url(post_id)
    if not saved:
        deps.notify(f"LinkedIn post out: {item['hook']}\n{url}\n\n⚠️ The log could not be pushed to GitHub. "
                    "The safety run one hour later may post the same item again: send /pause now and I will sort it out.")
        print(f"published {item['id']} but the log was not pushed: {url}")
        return 1
    deps.notify(f"LinkedIn post out ({fmt}): {item['hook']}\n{url}\n\n👉 Reply to every comment in the next hour: "
                "early replies are what make LinkedIn show it to more people.")
    print(f"published {item['id']}: {url}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", nargs="?", choices=["render", "prepare", "post"], default="render")
    ap.add_argument("--date", default="")
    a = ap.parse_args(argv)
    day = date.fromisoformat(a.date) if a.date else lagos_today()
    return run(a.mode, day)


if __name__ == "__main__":
    sys.exit(main())
