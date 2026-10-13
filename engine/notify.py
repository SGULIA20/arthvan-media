"""Telegram messages to the founder: what went out today, what failed, what needs him, what is coming.
Everything here is best-effort. A Telegram problem is printed and swallowed, because it must never fail a post.
Token and chat id: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from the environment, or from ~/arthvan-social/.env on the Mac."""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import telegram

ROOT = Path(__file__).resolve().parent.parent
BUFFER_TARGET = 7
NAMES = {"instagram": "Instagram", "youtube:sglearning": "YouTube (Learning with SG)", "youtube:arthvan": "YouTube (SG-MYTH-WORLD)",
         "threads": "Threads", "linkedin": "LinkedIn", "whatsapp": "WhatsApp", "telegram": "Telegram", "facebook": "Facebook", "x": "X"}
APP_NAMES = {"scoremybiz": "ScoreMyBiz", "waypoint": "Waypoint"}


def config(env=None):
    """{"token", "chat_id"} or None when Telegram is not set up here."""
    env = dict(os.environ if env is None else env)
    if not (env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID")):
        dotenv = Path(env.get("ARTHVAN_ENV") or Path.home() / "arthvan-social" / ".env")
        if dotenv.exists():
            for line in dotenv.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") and not env.get(k.strip()):
                    env[k.strip()] = v.strip().strip('"').strip("'")
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        return {"token": env["TELEGRAM_BOT_TOKEN"].strip(), "chat_id": env["TELEGRAM_CHAT_ID"].strip()}
    return None


def send(text: str, env=None, *, sender=telegram.send_message) -> bool:
    cfg = config(env)
    if not cfg:
        print("notify: Telegram is not set up here; message not sent")
        return False
    try:
        sender(cfg, text)
        return True
    except Exception as e:                                       # never let an alert break a run
        print(f"notify: could not send ({type(e).__name__}: {str(e).replace(cfg['token'], '<token>')[:150]})")
        return False


# ---------- reading the log ----------
def entries(log: Path) -> list:
    out = []
    if Path(log).exists():
        for line in Path(log).read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def day_state(log: Path, day: date) -> dict:
    """channel -> (status, item, note) for the day: the last entry per channel wins."""
    state = {}
    for e in entries(log):
        if e.get("date") == day.isoformat():
            state[e.get("channel", "instagram")] = (e.get("status"), e.get("item"), e.get("error") or e.get("note") or "", e.get("app"))
    return state


def _pretty(day: date) -> str:
    return f"{day.day} {day.strftime('%b')}"


def _channels(state: dict, wanted: str) -> list:
    return [NAMES.get(c, c) for c, v in state.items() if v[0] == wanted]


# ---------- what is ahead ----------
def buffer_days(root: Path, day: date, look: int = 21):
    """How many days after `day` already have a finished, claim-checked Reel in the calendar, counting without a gap."""
    from . import calendar_plan
    sched = calendar_plan.load_schedule(root) or {}
    by_id = {s["id"]: s for s in calendar_plan.load_stories(root)}
    n, last = 0, None
    for i in range(1, look + 1):
        d = day + timedelta(days=i)
        st = by_id.get(sched.get(d.isoformat()))
        if st and st["rendered"] and not st["problems"]:
            n, last = n + 1, d
        else:
            break
    return n, last


def upcoming(root: Path, day: date, days: int = 3) -> list:
    from . import calendar_plan
    sched = calendar_plan.load_schedule(root) or {}
    by_id = {s["id"]: s for s in calendar_plan.load_stories(root)}
    out = []
    for i in range(1, days + 1):
        d = day + timedelta(days=i)
        st = by_id.get(sched.get(d.isoformat()))
        out.append(f"{_pretty(d)}: {APP_NAMES.get(st['app'], st['app'])} · {st['id']}" if st else f"{_pretty(d)}: nothing planned")
    return out


def buffer_line(root: Path, day: date) -> str:
    n, last = buffer_days(root, day)
    if n >= BUFFER_TARGET:
        return f"Reels ready ahead: {n} days (through {_pretty(last)})."
    return f"⚠️ Only {n} day{'s' if n != 1 else ''} of finished Reels ahead, the target is {BUFFER_TARGET}." + (f" Last ready day: {_pretty(last)}." if last else "")


def reminders_due(root: Path, day: date) -> list:
    p = Path(root) / "content" / "reminders.json"
    if not p.exists():
        return []
    out = []
    for r in json.loads(p.read_text()):
        if r.get("on"):
            if r["on"] == day.isoformat():
                out.append(r["text"])
        elif r.get("from") and r.get("every_days"):
            start, end = date.fromisoformat(r["from"]), date.fromisoformat(r.get("until", "2999-01-01"))
            if start <= day <= end and (day - start).days % int(r["every_days"]) == 0:
                out.append(r["text"])
    return out


# ---------- the messages ----------
def daily_summary(root: Path, day: date) -> str:
    state = day_state(Path(root) / "logs" / "posts.jsonl", day)
    ig = state.get("instagram")
    item = ig[1] if ig else next(iter(state.values()), (None, "?"))[1]
    app = APP_NAMES.get(next((v[3] for v in state.values() if v[3]), None), "")
    done, bad = _channels(state, "published"), [c for c, v in state.items() if v[0] in ("failed", "waiting", "partial")]
    lines = [f"{'✅' if not bad else '⚠️'} {_pretty(day)}: {app + ' · ' if app else ''}{item}",
             "Posted on: " + (", ".join(done) if done else "nothing yet")]
    for c in bad:
        st, _item, note, _app = state[c]
        lines.append(f"Not posted on {NAMES.get(c, c)} ({st}): {note[:140]}")
    lines += ["", buffer_line(root, day), "Next: " + " | ".join(upcoming(root, day))]
    due = reminders_due(root, day)
    if due:
        lines += ["", "For you today:"] + [f"• {t}" for t in due]
    return "\n".join(lines)


def failure_alert(root: Path, day: date, run_url: str = "") -> str:
    state = day_state(Path(root) / "logs" / "posts.jsonl", day)
    bad = {c: v for c, v in state.items() if v[0] in ("failed", "waiting", "partial", "publishing")}
    lines = [f"⚠️ {_pretty(day)}: the daily post needs a look."]
    if not state:
        lines.append("Nothing was logged for today, so the run stopped before posting.")
    for c, (st, _item, note, _app) in bad.items():
        lines.append(f"• {NAMES.get(c, c)}: {st}" + (f" ({note[:140]})" if note else ""))
    if run_url:
        lines.append(f"Details: {run_url}")
    lines.append("The engine never posts twice on one day, so a retry is safe.")
    return "\n".join(lines)


def after_run(root: Path, day: date, code: int, entries_before: int, env=None, send_fn=None) -> None:
    """Called once per posting run. Failure -> alert. A run that posted something -> the day's summary. A no-op run -> silence."""
    send_fn = send_fn or send
    log = Path(root) / "logs" / "posts.jsonl"
    env = os.environ if env is None else env
    run_url = f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env.get('GITHUB_REPOSITORY')}/actions/runs/{env.get('GITHUB_RUN_ID')}" if env.get("GITHUB_RUN_ID") and env.get("GITHUB_REPOSITORY") else ""
    if code != 0:
        send_fn(failure_alert(root, day, run_url), env)
    elif len(entries(log)) > entries_before:
        send_fn(daily_summary(root, day), env)


def credit_line(today: date = None, ledger_path: Path = None) -> str:
    """Plain words for the Google trial credit: used, left, and the daily pace that would finish it by the deadline."""
    from . import broll
    p = broll.pace(ledger_path or broll.LEDGER, today)
    used, credit = round(p["spent_inr"]), round(p["credit_inr"])
    if p["finished"]:
        return f"Veo credit is finished: ₹{used:,} of ₹{credit:,} used. No more paid video is made."
    left = credit - used
    return (f"Veo credit: ₹{used:,} of ₹{credit:,} used ({round(100 * used / credit)}%). ₹{left:,.0f} is left for {p['days_left']} days, "
            f"about ₹{left / max(1, p['days_left']):,.0f} a day to use it all by 10 Dec.")


def digest_head(path: Path, limit: int = 2500) -> str:
    text = Path(path).read_text().strip()
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n…"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", action="store_true", help="send today's summary")
    ap.add_argument("--failure", action="store_true", help="send the failure alert for today")
    ap.add_argument("--credit", action="store_true", help="Mac only: credit pace and reel buffer")
    ap.add_argument("--weekly", help="path of the weekly report to send (with --link)")
    ap.add_argument("--link", default="")
    ap.add_argument("--text", help="send this text")
    ap.add_argument("--date")
    args = ap.parse_args(argv)
    day = date.fromisoformat(args.date) if args.date else (datetime.now(timezone.utc) + timedelta(hours=1)).date()
    if args.text:
        text = args.text
    elif args.daily:
        text = daily_summary(ROOT, day)
    elif args.failure:
        env = os.environ
        url = f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env.get('GITHUB_REPOSITORY')}/actions/runs/{env.get('GITHUB_RUN_ID')}" if env.get("GITHUB_RUN_ID") else ""
        text = failure_alert(ROOT, day, url)
    elif args.credit:
        text = "\n".join([credit_line(day), buffer_line(ROOT, day)] + [f"• {t}" for t in reminders_due(ROOT, day)])
    elif args.weekly:
        from . import coverage
        text = "\n".join(["Weekly report is ready." + (f" {args.link}" if args.link else ""), coverage.summary_line(ROOT), buffer_line(ROOT, day), "", digest_head(args.weekly)])
    else:
        ap.error("choose one of --daily --failure --credit --weekly --text")
    return 0 if send(text) else 1


if __name__ == "__main__":
    sys.exit(main())
