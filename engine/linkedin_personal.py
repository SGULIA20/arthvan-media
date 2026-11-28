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

# founder, 21 Nov 2026: the lane follows his own brief (content/prompts/linkedin-brief.md): seven categories of real companies, real
# numbers and management lessons, rotating over the three weekly slots. The five older names stay valid for posts already out.
CYCLE = ("case", "markets", "tools", "news", "leadership", "africa", "failure")
LIVE = ("markets", "news")           # need same-day facts: written the evening before behind a fact gate, never taken from the bank
CYCLE_START = date(2026, 11, 23)     # the first post under the brief (a Monday)
PILLARS = CYCLE + ("model", "finance", "ai", "world", "founder", "trend")
TREND_FIRST = True                   # founder, 25 Nov 2026 ("free to choose any topic worldwide"): each post starts from the week's most talked-about
                                     # business story, written the evening before behind the same fact gate; the day's category is the fallback
LABELS = {"case": "Case study", "markets": "Markets", "tools": "Management tools", "news": "Business news", "leadership": "Leadership",
          "africa": "Africa and emerging markets", "failure": "Business failures",
          "model": "Business model", "finance": "Finance", "ai": "AI for finance", "world": "World", "founder": "Founder notes",
          "trend": "This week's talking point"}
ACCENTS = {"case": "#F5B700", "markets": "#5EEAD4", "tools": "#C4B5FD", "news": "#FF9A7A", "leadership": "#7DD3FC", "africa": "#86EFAC",
           "failure": "#FCA5A5", "model": "#F5B700", "finance": "#5EEAD4", "ai": "#C4B5FD", "world": "#FF9A7A", "founder": "#7DD3FC", "trend": "#F5B700"}
CHANNEL = "linkedin_personal"
BANK = ROOT / "content" / "linkedin_personal.json"
TEMPLATE = ROOT / "engine" / "templates" / "linkedin_card.html"
SIZE = (1080, 1350)
MAX_HOOK, MAX_BODY, MAX_POST = 140, 1000, 1500     # hook: what a phone shows before "...see more" (founder, 25 Oct 2026)
POST_WEEKDAYS = (0, 2, 4)           # Mon, Wed, Fri (Lagos) only (founder, 29 Oct 2026: daily posts split the same ~360 readers, impressions fell 333 -> 31 a day)
DOC_WEEKDAYS = ()                   # 21 Nov 2026: no documents; his 25 Oct-21 Nov export gave pictures 127 impressions a post, documents 64
NEXT = "content/linkedin_next.json"  # the post chosen the evening before, so the founder's picture is made for the post that goes out
PICTURE_DIR = "inbox/linkedin"       # his picture for a day: inbox/linkedin/<YYYY-MM-DD>.jpg (the bot saves it from a photo captioned "li <date>")
# founder, 24 Nov 2026: "draft the posts with pics and let me post them. I think personal touch require there. Will fill it on your draft."
# Nothing is posted through the API any more: the evening message is his draft, the morning run hands him the text and the picture.
SELF_POST = True
DONE = ("published", "handed")       # a draft handed to him counts as used: the same post is not drafted again
TOUCH = {"case": "where you have seen this in a company you worked in or advised",
         "markets": "what this changes this week for your own business or the ones you advise",
         "tools": "one time you used this tool, or wish you had",
         "news": "what you would do about this if it were your company",
         "leadership": "a moment you led this way, or were led this way",
         "africa": "what you see of this on the ground in Lagos",
         "failure": "a mistake of your own that taught you the same lesson",
         "trend": "which side you take, and the one thing from your own work that makes you take it"}
BODY_WORDS = (100, 150)              # founder, 21 Nov 2026: "word limit should be similar as we posted so far" (the bank runs 107-144)
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
    words = len(str(item.get("body") or "").split())
    if item.get("pillar") in CYCLE + ("trend",) and not BODY_WORDS[0] <= words <= BODY_WORDS[1]:
        problems.append(f"body is {words} words, need {BODY_WORDS[0]} to {BODY_WORDS[1]}")
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
        if e.get("channel") == CHANNEL and e.get("status") in DONE and e.get("item"):
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


def post_days_between(start: date, day: date) -> int:
    """How many posting days lie from `start` up to but not including `day`."""
    n, d = 0, start
    while d < day:
        n += d.weekday() in POST_WEEKDAYS
        d += timedelta(days=1)
    return n


def category_for(day: date):
    """The brief's category for a posting day, or None before the brief began."""
    return None if day < CYCLE_START else CYCLE[post_days_between(CYCLE_START, day) % len(CYCLE)]


def choose(day: date, items: list, log: Path, settings: dict, root: Path = ROOT):
    """The post for `day`: the one fixed the evening before (so the founder's picture matches), else the first unused bank post of the
    day's category that passes the checks, else the first unused post of any bank category. None when nothing passes."""
    chosen = planned(root, day)
    if chosen and not lint_personal(chosen, settings):
        return chosen
    cat = category_for(day)
    queue = order(items, log)
    bank = [i for i in queue if i.get("pillar") not in LIVE]            # a live category is written that evening, never taken from the bank
    for cand in [i for i in bank if i.get("pillar") == cat] + [i for i in bank if i.get("pillar") != cat]:
        problems = lint_personal(cand, settings)
        if not problems:
            return cand
        print(f"lint rejected {cand['id']}: {problems}")
    return None


def planned(root: Path, day: date):
    """The post saved for `day` by the evening run: a bank id, or a whole post written that evening."""
    try:
        data = json.loads((Path(root) / NEXT).read_text())
    except (FileNotFoundError, ValueError):
        return None
    if data.get("date") != day.isoformat():
        return None
    if isinstance(data.get("item"), dict):
        return data["item"]
    return next((i for i in load_personal(root)["items"] if i["id"] == data.get("item_id")), None)


def founder_picture(root: Path, day: date):
    p = Path(root) / PICTURE_DIR / f"{day.isoformat()}.jpg"
    return p if p.exists() and p.stat().st_size > 10_000 else None


CHARTS = {"bar": "a bar chart", "line": "a line graph", "donut": "a donut chart", "waterfall": "a waterfall chart", "timeline": "a timeline",
          "process": "a process diagram", "map": "a geographical map", "kpi": "a KPI dashboard"}


def image_prompt(item: dict) -> str:
    """The picture prompt sent to the founder with the post. A photograph (his brief, section 6), or, when the post carries verified
    data, a data visual to his data-visualisation rules (21 Nov 2026): the exact figures are spelled out so nothing is invented."""
    c = (cards(item) or [{}])[0] if (item.get("card") or item.get("slides")) else {}
    v = item.get("visual") or {}
    data = v.get("data") or []
    if str(v.get("format") or "photo") != "photo" and len(data) >= 2:
        kind = CHARTS.get(str(v.get("chart")), "a data infographic" if v.get("format") == "infographic" else "a business comparison graphic")
        rows = "; ".join(f"{d.get('label')}: {d.get('value')}{(' ' + str(d['unit'])) if d.get('unit') else ''}" for d in data)
        return (f"Premium consulting-style data visual, 4:5 portrait, 1200 x 1500 pixels: {kind}. "
                f"Title at the top: \"{v.get('title') or c.get('title') or item['hook']}\". "
                f"Exact data, draw these values and no others, do not round, add or change any figure: {rows}. "
                f"Period, shown under the title: {v.get('period')}. Source line at the bottom, small: \"Source: {v.get('source')}\". "
                + (f"Highlight in one accent colour: {v['highlight']}. " if v.get("highlight") else "")
                + "Clean white or charcoal background, professional typography, a restrained palette of two or three colours, clear "
                "labels and data values on every mark, a legend only if it is needed. No decorative graphics, no icons that carry no "
                "data, no company logos, no photograph, no extra numbers or text.")
    scene = item.get("scene") or f"one clear, concrete scene that shows the subject of this post: {c.get('title') or item['hook']}"
    return (f"Photorealistic editorial business photograph, 4:5 portrait, 1200 x 1500 pixels. Scene: {scene}. "
            "Professional LinkedIn look: clean composition, one strong focal point, natural light, real textures, shallow depth of field. "
            "No text, no captions, no numbers, no watermark, no company logos or brand marks, no recognisable real person. "
            "Not a collage, not an infographic, no decorative elements.")


def visual_note(item: dict) -> str:
    """What the founder is told about the picture: the format chosen and why, and the figures to check his picture against."""
    v = item.get("visual") or {}
    data = v.get("data") or []
    if str(v.get("format") or "photo") == "photo" or len(data) < 2:
        return "Format: editorial photograph." + (f" {v['why']}" if v.get("why") else "")
    rows = "\n".join(f"  {d.get('label')}: {d.get('value')}{(' ' + str(d['unit'])) if d.get('unit') else ''}" for d in data)
    return (f"Format: {v.get('format')} ({v.get('chart') or 'graphic'}). {v.get('why') or ''}\n"
            f"⚠️ Picture tools often misdraw numbers. Before you send it, check every figure in the picture against this list:\n{rows}\n"
            f"Period: {v.get('period')} · Source: {v.get('source')}")


def next_post_day(now_utc: datetime) -> date:
    """The next posting day whose 08:00 Lagos is still ahead."""
    local = now_utc.astimezone(timezone(timedelta(hours=1)))
    d = local.date() if (local.hour, local.minute) < LINKEDIN_EARLIEST else local.date() + timedelta(days=1)
    while d.weekday() not in POST_WEEKDAYS:
        d += timedelta(days=1)
    return d


def evening(now_utc: datetime, *, root: Path = ROOT, deps=None, bank: dict = None) -> int:
    """The morning of a post, before 08:00 Lagos (until 25 Nov 2026 the evening before, hence the name): fix today's post, save it,
    and send the founder its text and picture prompt, once."""
    deps = deps or Deps()
    root = Path(root)
    day = next_post_day(now_utc)
    local = now_utc.astimezone(timezone(timedelta(hours=1)))
    if (day - local.date()).days > 0:                             # founder, 25 Nov 2026: written the same morning, not 12-15 hours before
        print(f"next post is {day}: its draft is written that morning, so the story is hours old, not a day")
        return 0
    deps.sync_repo()
    try:
        state = json.loads((root / NEXT).read_text())
    except (FileNotFoundError, ValueError):
        state = {}
    if state.get("date") == day.isoformat() and state.get("asked"):
        print(f"{day}: the picture was already asked for")
        return 0
    bank = bank or load_personal(root)
    log = root / "logs" / "posts.jsonl"
    cat, item, note = category_for(day), None, ""
    used = used_ids(log)
    covered = ([i["hook"] for i in bank["items"] if i["id"] in used] + [e.get("hook", "") for e in _entries(log) if e.get("hook")]
               + _own_posts(bank["settings"]))
    told = deps.review(root)                                      # his numbers, when new ones came in: lessons for tonight's writer
    if told:
        deps.git_publish(["logs/linkedin-lessons.json"], "linkedin: lessons from the last posts' numbers")
        deps.notify("📊 LinkedIn review of your last posts\n\n" + told.get("report", "") + "\n\nTonight's draft is written with this in mind.")
    if TREND_FIRST:
        item, why = deps.write_live("trend", day, covered, bank["settings"])
        if item is None:
            print(f"trend post did not pass ({why}); falling back to {cat}")
    if item is None and cat in LIVE:                                               # markets, news: researched and written now, used only past the fact gate
        item, why = deps.write_live(cat, day, covered, bank["settings"])
        if item is None:
            note = f"\n\nℹ️ A {LABELS[cat].lower()} post was due, but the fact check did not pass ({why}). A ready post from the bank goes out instead."
    item = item or choose(day, bank["items"], log, bank["settings"], root)
    if item is None:
        (root / NEXT).write_text(json.dumps({"date": day.isoformat(), "asked": True, "none": True}, indent=1) + "\n")    # told once, not on each evening slot
        deps.git_publish([NEXT], f"linkedin: nothing passes the checks for {day}")
        deps.notify(f"LinkedIn {day}: no post passes the checks, nothing is planned.")
        return 1
    text, tags = build_text(item, bank["settings"])
    in_bank = any(i["id"] == item["id"] for i in bank["items"])
    state = {"date": day.isoformat(), "asked": True, **({"item_id": item["id"]} if in_bank else {"item": item})}
    (root / NEXT).write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n")
    deps.git_publish([NEXT], f"linkedin: post planned for {day}")
    sources = ("\n\nSources checked:\n" + "\n".join(item["sources"][:4])) if item.get("sources") else ""
    if SELF_POST:
        deps.notify(f"✍️ LinkedIn DRAFT for {day:%a %d %b} ({LABELS[item['pillar']]}). You post this one yourself; best time 08:10 WAT.\n\n"
                    f"{text}\n\n{' '.join(tags)}{sources}{note}\n\n"
                    f"👉 YOUR TOUCH (add one or two lines in your own words, after the first paragraph): {TOUCH.get(item['pillar'], 'your own experience of this')}.")
        deps.notify(f"🖼 Picture for this draft\n\n{visual_note(item)}\n\nPrompt:\n{image_prompt(item)}\n\n"
                    f"Make it and post it with the draft. If you send it here as a PHOTO with the caption\nli {day.isoformat()}\n"
                    f"I hand it back with the final text at 08:10 WAT; without it you get the drawn card to use.")
        return 0
    deps.notify(f"🖼 LinkedIn post for {day:%a %d %b}, 08:10 WAT ({LABELS[item['pillar']]})\n\n{text}\n\n{' '.join(tags)}{sources}{note}")
    deps.notify(f"🖼 Picture for the LinkedIn post of {day:%a %d %b}\n\n{visual_note(item)}\n\nPrompt:\n{image_prompt(item)}\n\n"
                f"Send it to this bot as a PHOTO with the caption:\nli {day.isoformat()}\n\n"
                f"By 08:00 WAT. Without it the post still goes out, with the drawn card.")
    return 0


def composer_link(text: str, tags: list) -> str:
    """A link that opens LinkedIn's own post box with the text filled in (founder, 24 Nov 2026: "I will not need to do copy paste from
    somewhere"). LinkedIn's API cannot put a post into the app's Drafts, and a link cannot attach a picture: he adds that himself."""
    from urllib.parse import quote
    return "https://www.linkedin.com/feed/?shareActive=true&text=" + quote(f"{text}\n\n{' '.join(tags)}", safe="")


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


def _write_live(category: str, day: date, covered: list, settings: dict):
    from . import linkedin_live
    return linkedin_live.write(category, day, covered, settings)


def _own_posts(settings: dict) -> list:
    """Subjects he has posted about himself, in words the writer is shown: the check refuses them anyway, and a writer who is not
    told wastes its one try on them (27 Nov 2026: two samples running were about Nvidia, which he had just posted)."""
    return [f"anything about {x} (he posted on it himself)" for x in (settings.get("already_posted") or [])[-10:]]


def _review(root: Path):
    """New lessons from the numbers he sent, or None. Never raises: a failed review does not stop tomorrow's post."""
    try:
        from . import linkedin_live, linkedin_review
        return linkedin_review.review(root, lambda prompt: linkedin_live.call([{"role": "user", "content": prompt}], "You are a careful analyst.", searches=0)["text"])
    except Exception as e:                                    # noqa: BLE001
        print(f"linkedin review skipped: {type(e).__name__}: {str(e)[:150]}")
        return None


def _send_photo(path, caption: str = "") -> bool:
    """The picture to the founder's Telegram; never breaks the run."""
    from . import telegram
    cfg = notify.config(None)
    if not cfg:
        return False
    try:
        telegram.send_photo_file(cfg, path, caption)
        return True
    except Exception as e:                                    # noqa: BLE001
        print(f"picture not sent: {type(e).__name__}: {str(e)[:150]}")
        return False


@dataclass
class Deps:
    send_photo: Callable = field(default_factory=lambda: _send_photo)
    render_cards: Callable = render_cards
    post_images: Callable = linkedin.post_images
    post_document: Callable = linkedin.post_document
    make_pdf: Callable = linkedin.jpegs_to_pdf
    git_publish: Callable = _git_publish
    notify: Callable = field(default_factory=lambda: notify.send)
    sync_repo: Callable = _sync_repo
    sleep: Callable = time.sleep
    write_live: Callable = field(default_factory=lambda: _write_live)
    review: Callable = field(default_factory=lambda: _review)


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
    if mode == "post" and not SELF_POST and not (token and urn):
        print("LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN must be set")
        return 1
    if mode == "post" and day.weekday() not in POST_WEEKDAYS:
        print(f"{day}: not a LinkedIn day (Mon/Wed/Fri only), nothing posted")
        return 0
    bank = bank or load_personal(root)
    settings, items = bank["settings"], bank["items"]
    log = root / "logs" / "posts.jsonl"
    if mode == "post":
        deps.sync_repo()
        if day_status(log, day) in DONE:
            print(f"{day}: personal post already out or handed over, nothing to do")
            return 0
    item = choose(day, items, log, settings, root)
    if item is None:
        print("every item in the bank failed lint")
        if mode == "post" and day_status(log, day) != "told":       # once a day, not on each of the day's ten runs (24 Nov 2026)
            deps.notify("LinkedIn personal post: nothing went out today, every item in the bank failed lint.")
            _append(log, {"date": day.isoformat(), "channel": CHANNEL, "status": "told"}); _save_log(deps, log, f"log: {CHANNEL} told {day}")
        return 1
    entry = {"date": day.isoformat(), "channel": CHANNEL, "item": item["id"]}
    if str(item["id"]).startswith("live-"):
        entry["pillar"] = item["pillar"]
        entry["hook"] = item["hook"]                              # a live post is not in the bank: its subject is kept here against repeats

    def failed(what: str, e: Exception) -> int:
        print(f"{what} failed: {type(e).__name__}: {e}")
        if mode == "post":
            first = not any(e.get("channel") == CHANNEL and e.get("date") == day.isoformat() and e.get("status") == "failed"
                            and str(e.get("error", "")).startswith(f"{what}:") for e in _entries(log))   # a later run tries again; he is told once per kind of failure (24 Nov 2026)
            _append(log, dict(entry, status="failed", error=f"{what}: {type(e).__name__}: {str(e)[:250]}"))
            _save_log(deps, log, f"log: {CHANNEL} failed {day}")
            if first:
                deps.notify(f"LinkedIn personal post failed today ({item['id']}), {what}: {str(e)[:200]}")
        return 1

    mine = founder_picture(root, day)
    if mine:                                                  # 21 Nov 2026: the founder's own picture, made from the prompt sent the evening before
        paths = [mine]
    else:
        try:
            paths = deps.render_cards(item, root / "out" / "linkedin" / day.isoformat())
        except Exception as e:                                # noqa: BLE001  a blank picture or a Chromium crash
            return failed("picture", e)
    text, tags = build_text(item, settings)
    alts = [alt_text(c) for c in cards(item)][:len(paths)]
    print(f"{day} {item['id']} ({item['pillar']}): {len(paths)} picture(s)\n\n{text}\n\n{' '.join(tags)}\n")
    if mode != "post":
        return 0
    if SELF_POST:                                             # hand the draft and its picture to the founder; he posts it himself
        touch = TOUCH.get(item["pillar"], "your own experience of this")
        # 24 Nov 2026: the whole post was sent the evening before, again in the morning, and a third time inside the link. The morning
        # is now one message: the link that opens it written, and what to add. The text itself is in last evening's draft.
        deps.notify(f"✍️ Your LinkedIn post for today ({LABELS[item['pillar']]}): \"{str(item.get('hook', ''))[:90]}\"\n\n"
                    "📲 Tap to open LinkedIn with last evening's draft already written. Add your lines, attach the picture below, Post "
                    f"(08:10 WAT is the slot):\n{composer_link(text, tags)}\n\n👉 YOUR TOUCH: {touch}.\n\n"
                    "After posting, reply to every comment in the first hour.\n\n"
                    "📊 Tomorrow, send me a screenshot of this post's analytics as a PHOTO with the caption stats. "
                    "Those numbers decide how the next draft is written.")
        sent = deps.send_photo(paths[0], "The picture for today's LinkedIn post" + ("" if mine else " (the drawn card; your own picture was not sent)"))
        _append(log, dict(entry, status="handed", format="founder-picture" if mine else "picture", picture_sent=bool(sent)))
        _save_log(deps, log, f"log: {CHANNEL} handed to the founder {day}")
        print(f"handed {item['id']} to the founder")
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
    fmt = "founder-picture" if mine and fmt == "picture" else fmt
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


LINKEDIN_EARLIEST = (8, 0)                   # Lagos; the slot is 08:10


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", nargs="?", choices=["render", "prepare", "post", "evening", "trial"], default="render")
    ap.add_argument("--category", choices=LIVE + ("trend",), default="markets", help="trial: which live category to write a sample of")
    ap.add_argument("--date", default="")
    a = ap.parse_args(argv)
    if a.mode == "evening":
        return evening(datetime.now(timezone.utc))
    if a.mode == "trial":                                          # a sample of a live post, sent to the founder; nothing is saved or posted
        bank, today = load_personal(), lagos_today()
        item, why = _write_live(a.category, today, [i["hook"] for i in bank["items"]][:15] + _own_posts(bank["settings"]), bank["settings"])
        if item is None:
            notify.send(f"🧪 LinkedIn {a.category} sample: the fact check did not pass, so on a real evening the bank post would go out.\nReason: {why}")
            return 0
        text, tags = build_text(item, bank["settings"])
        notify.send(f"🧪 SAMPLE LinkedIn {a.category} post (not posted, not saved)\n\n{text}\n\n{' '.join(tags)}\n\nSources checked:\n"
                    + "\n".join(item["sources"][:4]) + f"\n\n{visual_note(item)}\n\nPicture prompt:\n{image_prompt(item)}")
        return 0
    day = date.fromisoformat(a.date) if a.date else lagos_today()
    if a.mode == "post" and not a.date:
        from .run_daily import too_early
        # 20 Nov 2026: the daily-post catch-up step, fired late by GitHub, published this at about 00:15 Lagos on 18 and 20 Nov, when
        # nobody is awake to answer the first comments; the slot is 08:10 Lagos (founder, 25 Oct 2026)
        if too_early(datetime.now(timezone.utc), LINKEDIN_EARLIEST):
            print(f"{day}: before {LINKEDIN_EARLIEST[0]:02d}:{LINKEDIN_EARLIEST[1]:02d} Lagos; nothing posted, the day waits for its slot")
            return 0
    return run(a.mode, day)


if __name__ == "__main__":
    sys.exit(main())
