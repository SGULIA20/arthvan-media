"""Feature coverage: every real feature of both apps gets a Reel (or is accounted for with a reason).

python -m engine.coverage             counts per app and bucket, and every feature still without a Reel
python -m engine.coverage --plan      assigns the uncovered features to dated slots up to 10 Dec and checks the credit

Buckets: reel (live, can be screenshotted), reel_needs_mock (live but no safe screenshot: needs a mock or filmed-only Reel),
conditional (plan-gated or India-only: shown with its conditions), waits_for_release (gated on a build not out yet),
not_ready (partial), not_live, not_advertised (safety, legal, admin; reason in content/coverage_rules.json).
A feature is covered when a Reel without claim problems has it as its hero feature or shows a screen that belongs to it.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import broll, claims
from .calendar_plan import build_plan, load_stories
from .config import ROOT
from .select_item import NO_REPEAT_DAYS, slot

DEADLINE = broll.DEADLINE
COST_PER_REEL = 6 * 8 * broll.INR_PER_SECOND      # six new eight-second shots


def rules(root: Path = ROOT) -> dict:
    p = Path(root) / "content" / "coverage_rules.json"
    return json.loads(p.read_text()).get("not_advertised", {}) if p.exists() else {}


def bucket(app: str, key: str, f: dict, na: dict):
    if f.get("status") == "general":
        return None
    if key in (na.get(app) or {}):
        return "not_advertised"
    st = f.get("status")
    if st == "not_live":
        return "not_live"
    if st == "partial" and not f.get("show_ok"):
        return "not_ready"
    if st == "gated" and not f.get("show_ok"):
        return "waits_for_release"
    if f.get("show_ok"):
        return "conditional"
    return "reel" if f.get("demo_possible") else "reel_needs_mock"


def covered(root: Path = ROOT) -> dict:
    """app -> feature -> sorted story ids that show it (hero feature or a mapped screen), ignoring Reels with claim problems."""
    feats, smap = claims.load(root)
    out = {"waypoint": {}, "scoremybiz": {}}
    for st in load_stories(root):
        if st.get("problems") or not st.get("rendered", True) and not st.get("scenes"):
            continue
        app = st["app"]; shown = {st.get("feature")} | {smap.get(app, {}).get(sc.get("screen")) for sc in st.get("scenes", []) if sc.get("screen")}
        shown |= set(st.get("also", []))
        for f in shown:
            if f:
                out[app].setdefault(f, set()).add(st["id"])
    return {a: {k: sorted(v) for k, v in d.items()} for a, d in out.items()}


def posts_cover(root: Path = ROOT) -> dict:
    out = {}
    for app in ("waypoint", "scoremybiz"):
        p = Path(root) / "content" / f"{app}.json"
        out[app] = {i.get("feature") for i in (json.loads(p.read_text()) if p.exists() else []) if i.get("feature")}
    return out


def report(root: Path = ROOT) -> dict:
    feats, _ = claims.load(root); na = rules(root); cov = covered(root); posts = posts_cover(root)
    res = {}
    for app in ("scoremybiz", "waypoint"):
        b = {}
        for key, f in (feats.get(app) or {}).items():
            k = bucket(app, key, f, na)
            if k is None:
                continue
            b.setdefault(k, []).append({"key": key, "name": f.get("name"), "reels": cov[app].get(key, []), "post": key in posts[app], "demo": bool(f.get("demo_possible")),
                                        "status": f.get("status"), "reason": (na.get(app) or {}).get(key) or f.get("gate")})
        res[app] = b
    return res


ADVERTISE = ("reel", "reel_needs_mock", "conditional")


def uncovered(root: Path = ROOT, app: str = None) -> list:
    r = report(root)
    out = []
    for a, b in r.items():
        if app and a != app:
            continue
        for k in ADVERTISE:
            for x in b.get(k, []):
                if not x["reels"]:
                    out.append((a, k, x))
    # demo-able live features first, then conditional, then the ones needing a mock
    order = {"reel": 0, "conditional": 1, "reel_needs_mock": 2}
    out.sort(key=lambda t: (order[t[1]], t[2]["key"]))
    return out


def plan_slots(today: date, root: Path = ROOT) -> dict:
    """The days up to the deadline that still need a new Reel, with each day's app: from the calendar planner."""
    stories = load_stories(root)
    for st in stories:
        if st.get("scenes"):
            st["rendered"] = True                         # written and queued for filming counts as taken
    sched = json.loads((Path(root) / "content" / "schedule.json").read_text()) if (Path(root) / "content" / "schedule.json").exists() else {}
    n = (DEADLINE - today).days + 1
    plan = build_plan(today, n, stories, keep={d: v for d, v in sched.items() if d <= (today + timedelta(days=1)).isoformat()})
    return {d: slot(date.fromisoformat(d)) for d, sid in plan.items() if not sid}



FAMILY = {  # ScoreMyBiz features grouped so one Reel can carry a hero feature and its natural companions
 "entry": ["sold-bought-spent-entry", "daily-totals-update", "same-every-month", "undo-after-remove", "entries-without-signal", "whatsapp-daily-update", "whatsapp-menu-reports", "voice-entry", "photo-entry"],
 "money": ["money-now", "money-to-collect", "money-to-pay", "customer-history", "customer-reminders", "evening-whatsapp-reminder", "sold-bought-spent-lists"],
 "books": ["cash-book-by-day", "profit-report", "profit-on-paper-vs-cash", "what-i-have-and-owe", "year-end-close", "file-for-accountant", "email-last-month-book", "who-changed-what", "lock-finished-month", "documents-from-my-ca"],
 "bills": ["bills-for-customers", "quotes-for-customers", "items-and-prices", "bills-tax-settings", "printable-daily-sheet"],
 "score": ["business-health-score", "score-from-my-book", "score-history", "risk-flags-behind-score", "compare-with-similar-shops", "personal-health-score", "share-score-picture", "share-my-week-picture", "streak-and-challenge"],
 "advice": ["ask-the-advisor", "next-moves", "reminders-in-my-words", "open-shop-and-sell-more-plans", "goals-and-timelines", "break-even", "what-if-simulator", "decision-practice", "decision-game", "free-calculators"],
 "reach": ["business-card", "offer-posters", "business-network", "schemes-and-weather", "invite-a-friend", "notifications-inbox", "works-in-your-language", "nineteen-countries", "free-month-and-plans"],
 "team": ["helpers-with-own-login", "several-shops", "ca-network"],
}
_ORDER = {k: (i, j) for i, (f, ks) in enumerate(FAMILY.items()) for j, k in enumerate(ks)}


def _chunk(items: list, slots: int) -> list:
    """Split items over `slots` days as evenly as possible (earlier days take the extra one)."""
    if slots <= 0:
        return []
    base, extra = divmod(len(items), slots); out = []; i = 0
    for d in range(slots):
        n = base + (1 if d < extra else 0); out.append(items[i:i + n]); i += n
    return out

def assign(today: date, root: Path = ROOT):
    """Every uncovered feature gets a dated slot. A day carries a hero feature and, when there are more features than
    days, its natural companions (same family). A day with nothing left is a localized version of an earlier Reel."""
    open_days = plan_slots(today, root)
    rows = []
    for app in ("scoremybiz", "waypoint"):
        days = sorted(d for d, (a, _l) in open_days.items() if a == app)
        items = [x for (aa, _k, x) in uncovered(root, app)]
        if app == "scoremybiz":
            items.sort(key=lambda x: _ORDER.get(x["key"], (99, 0)))
        for d, chunk in zip(days, _chunk(items, len(days))):
            rows.append({"date": d, "app": app, "lead": open_days[d][1], "hero": chunk[0]["key"] if chunk else None,
                         "also": [c["key"] for c in chunk[1:]], "names": [c["name"] for c in chunk]})
    rows.sort(key=lambda r_: r_["date"])
    return rows, {}


def queued_cost(root: Path = ROOT) -> float:
    """Credit the written but not yet filmed stories will take (new shots only)."""
    from .story import shot_plan
    total = 0.0
    for st in load_stories(root):
        if st.get("rendered") or st.get("problems") or not st.get("scenes"):
            continue
        total += sum(1 for p in shot_plan(st) if not p[3]) * 8 * broll.INR_PER_SECOND
    return total


def summary_line(root: Path = ROOT) -> str:
    r = report(root); tot = cov = 0
    for a, b in r.items():
        for k in ADVERTISE:
            for x in b.get(k, []):
                tot += 1; cov += bool(x["reels"])
    return f"Feature coverage: {cov} of {tot} advertisable features have a Reel."


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    r = report()
    for app in ("scoremybiz", "waypoint"):
        b = r[app]; total = sum(len(v) for v in b.values())
        print(f"\n== {app}: {total} features")
        for k in ("reel", "conditional", "reel_needs_mock", "waits_for_release", "not_ready", "not_live", "not_advertised"):
            xs = b.get(k, [])
            if xs:
                done = sum(1 for x in xs if x["reels"])
                print(f"  {k:18s} {len(xs):3d}" + (f"   with a Reel: {done}, without: {len(xs) - done}" if k in ADVERTISE else ""))
    print("\n" + summary_line())
    if "--plan" in argv:
        rows, _ = assign(date.today())
        print("\nOPEN DAYS to 10 Dec and the features each Reel will carry (hero first):")
        for r_ in rows:
            what = " + ".join(r_["names"]) if r_["hero"] else "-- localized version of an earlier Reel (same footage, new language and screens)"
            print(f"  {r_['date']}  {r_['app']:11s} {r_['lead']:6s}  {what}")
        n = len(rows); need = sum(1 for r_ in rows if r_["hero"])
        covered_after = sum(1 + len(r_["also"]) for r_ in rows if r_["hero"])
        print(f"\nFeatures placed in open days: {covered_after}; features without a slot: {len(uncovered()) - covered_after}")
        credit_left = broll.CREDIT_INR - broll.spent_inr()
        queued = queued_cost()
        after = credit_left - queued
        print(f"\nCredit left by my ledger: ₹{credit_left:.0f}; already queued (written, not yet filmed): ₹{queued:.0f}; after that: ₹{after:.0f}")
        print(f"{need} more Reels at about ₹{COST_PER_REEL:.0f} = ₹{need * COST_PER_REEL:.0f}  ->  " + ("fits" if need * COST_PER_REEL <= after else f"SHORT by ₹{need * COST_PER_REEL - after:.0f} (about {int((need * COST_PER_REEL - after) // COST_PER_REEL) + 1} Reels)"))
        if "--write" in argv:
            (ROOT / "content" / "production_queue.json").write_text(json.dumps([r_ for r_ in rows if r_["hero"]], indent=1, ensure_ascii=False) + "\n")
            print("written content/production_queue.json")
    else:
        print("\nWITHOUT A REEL YET (priority order):")
        for a, k, x in uncovered():
            print(f"  {a:11s} {k:15s} {x['key']:30s} {x['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
