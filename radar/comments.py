"""Weekly comment drafts: for the newest competitor and community videos the radar found, a short, genuinely useful
comment the founder can post by hand under his own name. No links, no pitch; the app is named at most once and only
where it belongs. Runs with the Monday report when a GEMINI_API_KEY is present.
python -m radar.comments          prints Markdown for the newest snapshot
"""
import json, re, sys
from pathlib import Path

from engine.gemini import GeminiError, ask
from engine.tts import api_key

HERE = Path(__file__).resolve().parent
PER_APP = 5
VOICE = {"scoremybiz": "a small-business owner who also runs a shop-health app called ScoreMyBiz",
         "waypoint": "someone who built a quiet app called Waypoint where people say one true sentence a day"}
RULES = ("Write one comment per video, in the same order, numbered. Each comment is one or two sentences, adds a real "
         "point or a small practical tip that fits the video's title, sounds like a person not a brand, and never asks "
         "anyone to download anything. No links, no hashtags, no emojis, no claims with numbers, no advice about health "
         "or safety. Name the app at most once across all comments, and only where it is natural. If a title is in "
         "Hindi or Hinglish, answer in easy Hinglish. Output only the numbered list.")


def newest_videos(snap: dict, app: str, prev: dict = None) -> list:
    """Up to PER_APP videos for the app, preferring ones not seen last week."""
    seen = set()
    if prev:
        for row in (prev.get("apps", {}).get(app) or {}).values():
            seen |= {v["id"] for v in row.get("youtube", [])}
    fresh, old = [], []
    for name, row in (snap.get("apps", {}).get(app) or {}).items():
        for v in row.get("youtube", []):
            (old if v["id"] in seen else fresh).append({"id": v["id"], "title": v["title"], "who": name})
    return (fresh + old)[:PER_APP]


def comments_prompt(app: str, vids: list) -> str:
    lines = [f"{i + 1}. [{v['who']}] {v['title']}" for i, v in enumerate(vids)]
    return f"You are {VOICE.get(app, 'a helpful viewer')}. Videos:\n" + "\n".join(lines) + "\n\n" + RULES


def _split(answer: str, n: int) -> list:
    parts = re.findall(r"^\s*\d+[.)]\s*(.+?)(?=^\s*\d+[.)]|\Z)", answer, re.S | re.M)
    parts = [re.sub(r"\s+", " ", p).strip().strip('"') for p in parts]
    return (parts + [""] * n)[:n]


def render(snap: dict, prev: dict = None) -> str:
    out = ["## Comment drafts (post by hand, under your own name)", ""]
    for app in snap.get("apps", {}):
        vids = newest_videos(snap, app, prev)
        if not vids:
            continue
        out.append(f"**{app}**"); out.append("")
        try:
            drafts = _split(ask(comments_prompt(app, vids)), len(vids))
        except GeminiError as e:
            out += [f"_drafts skipped: {e}_", ""]; continue
        for v, d in zip(vids, drafts):
            out.append(f"- [{v['title']}](https://www.youtube.com/watch?v={v['id']}) ({v['who']})")
            out.append(f"  > {d or '(no draft)'}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    if not api_key():
        print("_Comment drafts need GEMINI_API_KEY._"); return 0
    snaps = sorted((HERE / "snapshots").glob("*.json"))
    if not snaps:
        print("no snapshots"); return 1
    cur = json.loads(snaps[-1].read_text()); prev = json.loads(snaps[-2].read_text()) if len(snaps) > 1 else None
    print(render(cur, prev)); return 0


if __name__ == "__main__":
    sys.exit(main())
