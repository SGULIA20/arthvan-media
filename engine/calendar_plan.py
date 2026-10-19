"""The posting calendar for character Reels, planned ahead and written to content/schedule.json.

Rules (founder, 13 Oct 2026):
- one app and one lead a day, as select_item.slot says;
- an app never shows the same feature twice within 10 days;
- the Reels already made ("legacy": true in their story file) are all kept and used in between new Reels, never on
  two days in a row; a festival Reel is fixed to its date;
- a day with no suitable Reel is simply absent from the schedule and gets the normal graphics set.

python -m engine.calendar_plan 30            show the next 30 days
python -m engine.calendar_plan 30 --write    also write content/schedule.json (days already past are kept)
"""
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from .config import ROOT, production_mode
from . import claims
from .select_item import NO_REPEAT_DAYS, slot, story_lead

SCHEDULE = ROOT / "content" / "schedule.json"


def load_schedule(root: Path = ROOT):
    p = Path(root) / "content" / "schedule.json"
    return json.loads(p.read_text()) if p.exists() else None


STORY_MAX_SECONDS = 60.0


def video_seconds(path: Path):
    """Length of a finished Reel in seconds, or None when it cannot be read (the guard then stays quiet)."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def load_stories(root: Path = ROOT) -> list:
    out = []
    feats_smap = claims.load(root)
    for p in sorted((Path(root) / "stories").glob("*.json")):
        try:
            st = json.loads(p.read_text())
        except ValueError:
            continue
        if st.get("id") and st.get("app"):
            video = Path(root) / "stories" / "out" / f"{st['id']}.mp4"
            st["rendered"] = video.exists()
            st["problems"] = claims.story_problems(st, *feats_smap)
            secs = video_seconds(video) if st["rendered"] else None
            if secs is not None and secs > STORY_MAX_SECONDS:
                st["problems"].append(f"video is {secs:.0f} s, over the {STORY_MAX_SECONDS:.0f} s Instagram Story limit")
            out.append(st)
    return out


def build_plan(start: date, days: int, stories: list, *, published: dict = None, feature_log: list = None, keep: dict = None, story_only: bool = False) -> dict:
    """date-iso -> story id or None, for `days` days from `start`.
    published: story id -> date it went out; feature_log: [(date-iso, app, feature)] already posted; keep: dates before start.
    story_only (production mode "stories", founder 19 Oct 2026): only illustrated story Reels (those with an "art" block) are planned,
    and the male/female lead alternation is ignored (every story is told by the same narrator; only the app still alternates)."""
    published = published or {}
    if story_only:
        stories = [s for s in stories if s.get("art")]
    log = [tuple(x) for x in (feature_log or [])]
    plan = dict(keep or {})
    used = set(published) | {v for k, v in plan.items() if v}
    by_id = {s["id"]: s for s in stories}
    stories = [s for s in stories if not s.get("problems")]          # nothing false or premature is ever planned
    fixed = {s["post_on"]: s for s in stories if s.get("occasion") and s.get("rendered") and s.get("post_on")}

    def recent(app, d):
        lo = (d - timedelta(days=NO_REPEAT_DAYS)).isoformat()
        return {f for (when, a, f) in log if a == app and lo <= when < d.isoformat()}

    def near_festival_with(app, feature, d):
        """A festival Reel fixed within 10 days of d (either side) already shows this feature for this app."""
        for iso2, fs in fixed.items():
            if fs["app"] == app and fs.get("feature") == feature and iso2 != d.isoformat() \
                    and abs((date.fromisoformat(iso2) - d).days) <= NO_REPEAT_DAYS:
                return True
        return False

    def is_legacy(sid):
        return bool(sid) and bool(by_id.get(sid, {}).get("legacy") or by_id.get(sid, {}).get("occasion"))

    for i in range(days):
        d = start + timedelta(days=i); iso = d.isoformat()
        if (keep or {}).get(iso):                     # pinned: this day already has its Reel
            sid = keep[iso]
            if sid in by_id:
                log.append((iso, by_id[sid]["app"], by_id[sid].get("feature")))
            continue
        prev_legacy = is_legacy(plan.get((d - timedelta(days=1)).isoformat()))
        nxt = fixed.get((d + timedelta(days=1)).isoformat())
        next_fixed_legacy = bool(nxt and nxt["id"] not in used)
        pick = None
        if iso in fixed and fixed[iso]["id"] not in used:
            pick = fixed[iso]
        else:
            app, lead = slot(d)
            avoid = recent(app, d)
            cands = [s for s in stories
                     if s.get("rendered") and s["id"] not in used and not s.get("occasion")
                     and s["app"] == app and (story_only or story_lead(s) == lead) and (s.get("post_on") or "0") <= iso
                     and s.get("feature") not in avoid and not near_festival_with(app, s.get("feature"), d)
                     and not (s.get("legacy") and (prev_legacy or next_fixed_legacy))]
            cands.sort(key=lambda s: (bool(s.get("legacy")), s.get("post_on") or "", s["id"]))
            pick = cands[0] if cands else None
        plan[iso] = pick["id"] if pick else None
        if pick:
            used.add(pick["id"]); log.append((iso, pick["app"], pick.get("feature")))
    return plan


def violations(plan: dict, stories: list) -> list:
    """Rule breaches in a plan (used by the tests and printed by the CLI)."""
    by_id = {s["id"]: s for s in stories}; bad = []
    days = sorted(plan)
    for d in days:
        if plan[d] and by_id.get(plan[d], {}).get("problems"):
            bad.append(f"{d}: {plan[d]} has claim problems: {by_id[plan[d]]['problems'][0]}")
    for k, d in enumerate(days):
        sid = plan[d]
        if not sid:
            continue
        s = by_id[sid]
        if (s["app"], story_lead(s)) != slot(date.fromisoformat(d)) and not s.get("occasion"):
            bad.append(f"{d}: {sid} is not this day's app and lead")
        for e in days[:k]:
            o = plan[e]
            if o and by_id[o]["app"] == s["app"] and by_id[o].get("feature") == s.get("feature") \
                    and (date.fromisoformat(d) - date.fromisoformat(e)).days <= NO_REPEAT_DAYS:
                bad.append(f"{d}: {s.get('feature')} for {s['app']} was already shown on {e}")
        if k and plan[days[k - 1]] and (s.get("legacy") or s.get("occasion")) and (by_id[plan[days[k - 1]]].get("legacy") or by_id[plan[days[k - 1]]].get("occasion")) \
                and (date.fromisoformat(d) - date.fromisoformat(days[k - 1])).days == 1 and not (s.get("occasion") and by_id[plan[days[k - 1]]].get("occasion")):
            bad.append(f"{d}: two earlier-made Reels in a row ({plan[days[k - 1]]}, {sid})")
    return bad


def planned_features(root: Path, app: str, day: date, days: int = NO_REPEAT_DAYS) -> list:
    """Features of Reels already planned for this app in the coming `days` days, so a graphics post never lands on them."""
    sched = load_schedule(root)
    if not sched:
        return []
    by_id = {s["id"]: s for s in load_stories(root)}
    out = []
    for d, sid in sched.items():
        if sid and day < date.fromisoformat(d) <= day + timedelta(days=days) and by_id.get(sid, {}).get("app") == app:
            f = by_id[sid].get("feature")
            if f:
                out.append(f)
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    n = int(argv[0]) if argv and argv[0].isdigit() else 30
    write = "--write" in argv
    today = date.today()
    stories = load_stories()
    published, feature_log = {}, []
    logf = ROOT / "logs" / "posts.jsonl"
    if logf.exists():
        for line in logf.read_text().splitlines():
            e = json.loads(line)
            if e.get("status") == "published" and e.get("channel", "instagram") == "instagram":
                published[e["item"]] = e["date"]
                if e.get("feature"):
                    feature_log.append((e["date"], e.get("app"), e["feature"]))
    old = load_schedule() or {}
    keep = {d: v for d, v in old.items() if d < today.isoformat()}
    for a in argv:                                   # --keep 2026-10-13=mira-window-en : this day keeps this Reel
        if "=" in a and a[:2] != "--":
            d, sid = a.split("=", 1); keep[d] = sid
    start = today
    story_only = production_mode() == "stories"
    plan = build_plan(start, n, stories, published=published, feature_log=feature_log, keep=keep, story_only=story_only)
    by_id = {s["id"]: s for s in stories}
    if story_only:
        print("production mode: stories (only illustrated story Reels are planned)")
    print("date        slot                       Reel")
    for d in sorted(plan):
        if d < today.isoformat():
            continue
        sid = plan[d]; sl = slot(date.fromisoformat(d))
        tag = "" if not sid else (" [earlier-made]" if by_id[sid].get("legacy") else (" [festival]" if by_id[sid].get("occasion") else " [new]"))
        print(f"{d}  {sl[0]:11s} {sl[1]:7s}  {(sid or '-- graphics set; Reel still to make --')}{tag}  {by_id[sid].get('feature') if sid else ''}")
    held = [x for x in stories if x.get("rendered") and x.get("problems")]
    for x in held:
        print(f"HELD BACK: {x['id']}: {x['problems'][0]}" + (f" (+{len(x['problems']) - 1} more)" if len(x['problems']) > 1 else ""))
    for v in violations({d: x for d, x in plan.items() if d >= today.isoformat()}, stories):
        print("RULE BREACH:", v)
    if write:
        SCHEDULE.write_text(json.dumps({d: plan[d] for d in sorted(plan) if plan[d]}, indent=1) + "\n")
        print("written:", SCHEDULE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
