"""The LinkedIn post-mortem (founder, 25 Nov 2026: "additional steps for LinkedIn as well like we did for YouTube channels to make
posts viral from choosing the topics to postmortem").

LinkedIn gives this app no numbers (the analytics API answers 403, logs/linkedin-diagnosis.json) and the founder posts by hand, so
the numbers come from him: a screenshot of a post's analytics, or of his list of posts, sent to the bot as a PHOTO captioned `stats`.
Gemini reads the figures off the picture; only the figures are kept (logs/linkedin-stats.json). The screenshot itself is never saved:
this repository is public.

Once three posts have numbers, the evening run asks Claude what the best ones share and the weakest lack, and keeps at most five
lessons (logs/linkedin-lessons.json). The writer of the next draft is given them. A finding is acted on, not only reported.
"""
import base64
import difflib
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from .config import ROOT

STATS = "logs/linkedin-stats.json"
LESSONS = "logs/linkedin-lessons.json"
CHANNEL = "linkedin_personal"
MODEL = "gemini-3.8-flash"
MIN_POSTS = 3                           # fewer posts than this cannot be compared
LOOK_BACK = 14                          # posts a screenshot may be matched to
MATCH = 0.55                            # how alike a line read off the picture and a post's opening must be
STATS_RE = re.compile(r"^\s*stats(?:\s+(\d{4}-\d{2}-\d{2}))?\s*$", re.I)
READ = """This is a screenshot from the LinkedIn app: the analytics of one post, or a list of the member's posts with their numbers.
Read only what is printed. For each post you can see, give the first words of its text (as many as are visible, up to 15) and its
numbers. Use null for a number that is not shown; never estimate. "1,234" is 1234 and "1.2K" is 1200.
Reply with JSON only: {"posts": [{"first_line": "...", "impressions": 0, "reactions": 0, "comments": 0, "reposts": 0, "members_reached": 0, "profile_views": 0, "followers_gained": 0}]}"""
FIELDS = ("impressions", "reactions", "comments", "reposts", "members_reached", "profile_views", "followers_gained")
REVIEW = """You review a senior finance and operations executive's LinkedIn posts so the NEXT post does better. Below are his recent
posts with the numbers LinkedIn showed him. Impressions measure reach; comments and reposts matter more than reactions, because they
are what makes LinkedIn show a post to more people.

Compare the best with the weakest. Look at the subject, the first line (the only part shown before "see more"), whether the post names
a company or a figure, whether it takes a side, the closing question and the picture format. Say only what these posts show; with so
few posts a pattern is a direction, not proof, and where the numbers cannot tell two things apart, say so.

Reply with JSON only:
{"lessons": ["at most 5; each one instruction the writer of the next post can follow, with the posts and numbers it rests on"],
 "best": "which post did best and what it did, one sentence", "worst": "which did worst and why, one sentence",
 "subjects": "what kind of subject to choose next and what to avoid, one sentence",
 "report": "at most 5 short plain lines for the owner: what worked, what did not, and the one change made to the next draft"}

POSTS
"""


def is_stats(message: dict) -> bool:
    return bool(STATS_RE.match(message.get("caption") or ""))


def stats_day(message: dict) -> str:
    m = STATS_RE.match(message.get("caption") or "")
    return (m.group(1) or "") if m else ""


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(m.group(0)) if m else {}


def read_shot(path: Path, *, key: str = None, req=None) -> list:
    """The posts and numbers printed on a screenshot."""
    from . import xray
    from .tts import api_key
    key = api_key() if key is None else key
    if not key:
        raise ValueError("GEMINI_API_KEY is not set")
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(Path(path).read_bytes()).decode()}},
                                    {"text": READ}]}], "generationConfig": {"maxOutputTokens": 4000, "temperature": 0}}
    _h, raw = (req or xray._req)(f"{xray.BASE}/v1beta/models/{MODEL}:generateContent", method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    d = json.loads(raw)
    text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
    return [p for p in _json(text).get("posts") or [] if isinstance(p, dict)]


def load(root: Path = ROOT, name: str = STATS) -> dict:
    try:
        return json.loads((Path(root) / name).read_text())
    except (FileNotFoundError, ValueError):
        return {}


def recent_posts(root: Path = ROOT) -> list:
    """The lane's last posts that went out or were handed to him: date, id, category and opening line."""
    from . import linkedin_personal as lp
    bank = {i["id"]: i for i in lp.load_personal(root)["items"]}
    out = {}
    for e in lp._entries(Path(root) / "logs" / "posts.jsonl"):
        if e.get("channel") != CHANNEL or e.get("status") not in lp.DONE:
            continue
        item = bank.get(e.get("item"), {})
        out[e["date"]] = {"date": e["date"], "item": e.get("item"), "pillar": e.get("pillar") or item.get("pillar") or "",
                          "hook": e.get("hook") or item.get("hook") or "", "format": e.get("format") or ""}
    return sorted(out.values(), key=lambda p: p["date"])[-LOOK_BACK:]


def _alike(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", str(s).lower())[:90]
    a, b = norm(a), norm(b)
    return difflib.SequenceMatcher(None, a[:len(b)] if len(b) < len(a) else a, b[:len(a)] if len(a) < len(b) else b).ratio() if a and b else 0.0


def match(read: list, posts: list, day: str = "") -> tuple:
    """Each post read off the picture, paired with one of ours by its opening words (he may have added his own lines after the first
    paragraph; the opening is ours). A single post with a date in the caption is taken on his word. Returns (pairs, unmatched)."""
    pairs, lost = [], []
    for r in read:
        if not any(isinstance(r.get(f), (int, float)) for f in FIELDS):
            continue
        if day and len(read) == 1:
            ours = next((p for p in posts if p["date"] == day), None) or {"date": day, "item": "", "pillar": "", "hook": str(r.get("first_line") or ""), "format": ""}
        else:
            ours = max(posts, key=lambda p: _alike(r.get("first_line"), p["hook"]), default=None)
            if not ours or _alike(r.get("first_line"), ours["hook"]) < MATCH:
                lost.append(str(r.get("first_line") or "")[:60])
                continue
        pairs.append((ours, {f: int(r[f]) for f in FIELDS if isinstance(r.get(f), (int, float))}))
    return pairs, lost


def record(root: Path, pairs: list, today: date) -> dict:
    """Keep the figures: the latest reading of a post replaces the earlier one (numbers only grow)."""
    data = load(root)
    posts = data.setdefault("posts", {})
    for ours, nums in pairs:
        posts[ours["date"]] = {**{k: ours.get(k, "") for k in ("item", "pillar", "hook", "format")}, **nums, "read_on": today.isoformat()}
    p = Path(root) / STATS
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return data


def stats_reply(cfg: dict, message: dict, root: Path, *, call=None, change=None, fetch=None, read=read_shot, today: date = None) -> str:
    """A screenshot captioned `stats`: its numbers are read and kept, and he is told exactly what was read so a misread shows."""
    from . import tg_commands as tg
    pic = tg.picture_of(message)
    tmp = Path(root) / "out" / "stats-shot.jpg"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        (fetch or tg.download)(cfg, pic["file_id"], tmp, call)
        seen = read(tmp)
    except Exception as e:                                    # noqa: BLE001
        return f"📊 I could not read that screenshot ({type(e).__name__}: {str(e)[:120]}). Send it again in a few minutes."
    finally:
        tmp.unlink(missing_ok=True)                           # the picture is never kept: only the figures are
    pairs, lost = match(seen, recent_posts(root), stats_day(message))
    if not pairs:
        return ("📊 I could not tie that screenshot to one of our posts"
                + (f" (I read: \"{lost[0]}\")" if lost else " (no numbers were readable)")
                + ". Send the post's analytics screen with the caption\nstats 2026-11-25\nusing the date the post went out.")
    record(root, pairs, today or datetime.now(timezone.utc).date())
    try:
        (change or tg.git_change)(root, [STATS], [], "linkedin: post numbers from the founder's screenshot")
    except Exception as e:                                    # noqa: BLE001
        return f"📊 Numbers read but not saved to git ({str(e)[:120]}). Send the screenshot again in a few minutes."
    lines = [f"• {o['date']} \"{o['hook'][:50]}\": " + ", ".join(f"{v:,} {k.replace('_', ' ')}" for k, v in n.items()) for o, n in pairs]
    have = len(load(root).get("posts", {}))
    tail = ("The next draft is written with these in mind." if have >= MIN_POSTS
            else f"{have} of {MIN_POSTS} posts have numbers; the review starts at {MIN_POSTS}.")
    return "📊 Read from your screenshot:\n" + "\n".join(lines) + ("\nNot matched: " + "; ".join(lost) if lost else "") + f"\n\nIf a number is wrong, send a clearer screenshot. {tail}"


def _mark(posts: dict) -> str:
    return hashlib.sha256(json.dumps(posts, sort_keys=True).encode()).hexdigest()[:16]


def review(root: Path = ROOT, ask=None, today: date = None):
    """New lessons when the numbers have changed since the last review; None when there is nothing new or too little to compare.
    `ask(prompt) -> text` is a plain Claude request."""
    posts = load(root).get("posts") or {}
    old = load(root, LESSONS)
    if len(posts) < MIN_POSTS or old.get("mark") == _mark(posts):
        return None
    rows = [{"date": d, **{k: v for k, v in p.items() if k != "read_on"}} for d, p in sorted(posts.items())[-LOOK_BACK:]]
    r = _json(ask(REVIEW + json.dumps(rows, ensure_ascii=False, indent=1)))
    lessons = [str(x).strip() for x in r.get("lessons") or [] if str(x).strip()][:5]
    if not lessons:
        return None
    out = {"date": (today or datetime.now(timezone.utc).date()).isoformat(), "mark": _mark(posts), "posts": len(rows), "lessons": lessons,
           **{k: str(r.get(k) or "")[:600] for k in ("best", "worst", "subjects", "report")}}
    (Path(root) / LESSONS).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    return out


def lesson_text(root: Path = ROOT) -> str:
    """What the writer of the next post is told. Empty until a review exists."""
    d = load(root, LESSONS)
    if not d.get("lessons"):
        return ""
    return ("\n\nWHAT HIS OWN POSTS HAVE SHOWN (from the numbers of his last " + str(d.get("posts")) + " posts; follow these):\n- "
            + "\n- ".join(d["lessons"]) + (f"\nSubjects: {d['subjects']}" if d.get("subjects") else ""))
