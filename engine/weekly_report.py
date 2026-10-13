"""Saturday report to the founder's Telegram: users in both apps, and what was spent where.
Runs on the Mac (the Google credit ledger lives there; the Supabase CLI is already logged in there).
It reads COUNTS only: one number per question, no names, phones or messages. Anything it cannot read is said plainly,
never guessed.   python -m engine.weekly_report [--dry]   (--dry prints instead of sending)"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import broll, notify

STATE = Path.home() / "arthvan-social" / "logs" / "weekly-state.json"
ENV_FILE = Path.home() / "arthvan-social" / ".env"
PROJECTS = [
    ("ScoreMyBiz", "xiidltxcsetevaverqkx",
     "select count(*) as total, count(*) filter (where registered_at >= now() - interval '7 days') as new_7d, "
     "count(*) filter (where plan in ('starter','growth')) as paid from public.users"),
    ("Waypoint", "zoyopcfnglpcnlraokob",
     "select count(*) as total, count(*) filter (where created_at >= now() - interval '7 days') as new_7d from auth.users"),
]


def _rows(obj):
    """The first list of dicts anywhere in the CLI's JSON (its exact wrapper differs between versions)."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            return obj
        for x in obj:
            r = _rows(x)
            if r:
                return r
    elif isinstance(obj, dict):
        for v in obj.values():
            r = _rows(v)
            if r:
                return r
    return []


def user_counts(ref: str, sql: str, run=subprocess.run) -> dict:
    got = run(["supabase", "db", "query", "--project-ref", ref, "--output-format", "json", sql], capture_output=True, text=True, timeout=120)
    if got.returncode != 0:
        raise RuntimeError((got.stderr or got.stdout).strip().splitlines()[-1][:150] if (got.stderr or got.stdout).strip() else "the query failed")
    rows = _rows(json.loads(got.stdout[got.stdout.index(next(c for c in got.stdout if c in "[{")):]))
    if not rows:
        raise RuntimeError("the answer had no rows")
    return {k: int(v) for k, v in rows[0].items() if v is not None}


def env_value(name: str, env_file: Path = ENV_FILE) -> str:
    if os.environ.get(name):
        return os.environ[name]
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return ""


def wallet_usd(app_id: str, api_key: str, opener=urllib.request.urlopen) -> float:
    req = urllib.request.Request(f"https://api.gupshup.io/wa/app/{app_id}/wallet/balance", headers={"apikey": api_key})
    with opener(req, timeout=30) as r:
        return float(json.load(r)["wallet"]["balance"])


def _signed(n, fmt="{:,.0f}") -> str:
    return ("+" if n >= 0 else "−") + fmt.format(abs(n))


def build(day: date, *, run=subprocess.run, wallet=None, state_path: Path = STATE, ledger: Path = broll.LEDGER) -> tuple:
    """(text, new_state). `wallet` is a callable returning the USD balance, or None when it is not set up."""
    try:
        last = json.loads(Path(state_path).read_text())
    except (OSError, ValueError):
        last = {}
    state = {"date": day.isoformat(), "users": {}}
    lines = [f"📊 Weekly report, {day.day} {day.strftime('%b')}", "", "Users"]
    for name, ref, sql in PROJECTS:
        try:
            c = user_counts(ref, sql, run)
            state["users"][name] = c["total"]
            prev = (last.get("users") or {}).get(name)
            extra = f", {c['paid']} paid" if "paid" in c else ""
            change = f" ({_signed(c['total'] - prev)} since last report)" if prev is not None else ""
            lines.append(f"• {name}: {c['total']} in total, {c['new_7d']} new in the last 7 days{extra}{change}")
        except Exception as e:
            lines.append(f"• {name}: could not read ({str(e)[:110]})")
    lines += ["", "Spend so far"]
    used = round(broll.spent_inr(ledger))
    prev_used = last.get("veo_inr")
    state["veo_inr"] = used
    lines.append(notify.credit_line(day, ledger) + (f" This week: {_signed(used - prev_used, '₹{:,.0f}')}." if prev_used is not None else ""))
    if wallet:
        try:
            bal = wallet()
            state["wallet_usd"] = bal
            prev_w = last.get("wallet_usd")
            lines.append(f"• WhatsApp wallet (Gupshup): ${bal:.2f} left" + (f"; used ${max(0.0, prev_w - bal):.2f} this week" if prev_w is not None and prev_w >= bal else (f"; topped up since last report" if prev_w is not None else "")) + ".")
        except Exception as e:
            lines.append(f"• WhatsApp wallet (Gupshup): could not read ({str(e)[:90]}).")
    else:
        lines.append("• WhatsApp wallet (Gupshup): not connected to this report yet.")
    lines += ["• Claude (Anthropic): code cannot read this; see console.anthropic.com → Usage.",
              "• Gemini (voice notes, photo scans, Reel voices): code cannot read this; see aistudio.google.com → Usage.",
              "Netlify, Supabase and GitHub are on fixed plans, so there is no per-use bill to show."]
    return "\n".join(lines), state


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    day = (datetime.now(timezone.utc) + timedelta(hours=1)).date()
    app_id, key = env_value("GUPSHUP_APP_ID"), env_value("GUPSHUP_API_KEY")
    text, state = build(day, wallet=(lambda: wallet_usd(app_id, key)) if app_id and key else None)
    if "--dry" in argv:
        print(text)
        return 0
    if not notify.send(text):
        return 1
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
