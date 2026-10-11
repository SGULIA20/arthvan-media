"""Weekly Instagram performance report: reach, views, likes, comments, saves, shares for the last 7 days.

python -m engine.digest            writes docs/reports/YYYY-MM-DD.md and prints it
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT
from .instagram import InstagramError, call

METRICS = "reach,views,saves,shares"
LABEL = {"REELS": "Reel", "FEED": "Post", "STORY": "Story"}


def collect(token: str, week_end: date) -> dict:
    """Media published in the 7 days ending on week_end (UTC), each with its insight numbers."""
    start = datetime.combine(week_end - timedelta(days=7), datetime.min.time(), timezone.utc)
    media = call("GET", "/me/media", token, {
        "fields": "id,media_product_type,media_type,permalink,timestamp,caption,like_count,comments_count",
        "limit": "50"}).get("data", [])
    rows = []
    for m in media:
        when = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if when < start:
            continue
        row = dict(m, reach=None, views=None, saves=None, shares=None)
        try:
            ins = call("GET", f"/{m['id']}/insights", token, {"metric": METRICS}).get("data", [])
            for i in ins:
                row[i["name"]] = i["values"][0]["value"] if i.get("values") else None
        except InstagramError as e:
            row["note"] = str(e)[:120]
        rows.append(row)
    rows.sort(key=lambda r: r["timestamp"])
    followers = call("GET", "/me", token, {"fields": "followers_count"}).get("followers_count")
    return {"followers": followers, "week_end": week_end, "media": rows}


def _n(v):
    return "-" if v is None else f"{v:,}"


def render_markdown(rep: dict, posted: dict) -> str:
    """posted: date string -> {app, item} from logs/posts.jsonl, to name what each post was."""
    rows = sorted(rep["media"], key=lambda r: (r["reach"] or 0), reverse=True)
    out = [f"# Weekly report to {rep['week_end']}", "", f"Followers: {_n(rep['followers'])}", "",
           "| Date | Format | App | Item | Reach | Views | Likes | Comments | Saves | Shares | Link |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        day = r["timestamp"][:10]
        who = posted.get(day, {})
        out.append(f"| {day} | {LABEL.get(r['media_product_type'], r['media_product_type'])} | {who.get('app', '-')} | "
                   f"{who.get('item', '-')} | {_n(r['reach'])} | {_n(r['views'])} | {_n(r.get('like_count'))} | "
                   f"{_n(r.get('comments_count'))} | {_n(r["saves"])} | {_n(r['shares'])} | [open]({r['permalink']}) |")
    reach = sum(r["reach"] or 0 for r in rows)
    likes = sum(r.get("like_count") or 0 for r in rows)
    out += ["", f"Total reach: {_n(reach)}. Total likes: {_n(likes)}. Posts: {len(rows)}.", ""]
    if rows:
        best = rows[0]
        out.append(f"Best reach: {LABEL.get(best['media_product_type'], '')} on {best['timestamp'][:10]} "
                   f"({posted.get(best['timestamp'][:10], {}).get('item', 'unknown item')}).")
    return "\n".join(out) + "\n"


def posted_index(log: Path) -> dict:
    out = {}
    if log.exists():
        for line in log.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("status") == "published" and e.get("channel", "instagram") == "instagram":
                out[e["date"]] = {"app": e.get("app"), "item": e.get("item")}
    return out


def main() -> int:
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        print("IG_ACCESS_TOKEN is not set")
        return 1
    today = date.today()
    rep = collect(token, today)
    md = render_markdown(rep, posted_index(ROOT / "logs" / "posts.jsonl"))
    out = ROOT / "docs" / "reports" / f"{today}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
