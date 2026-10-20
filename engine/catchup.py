"""Whatever this Mac still owes, whenever it happens to be on (the founder switches the laptop on at no fixed time; launchd calendar jobs
are lost while it is off). One launch agent, com.arthvan.catchup, runs this at login and every 30 minutes; each duty runs at most once per
period and only when due, so a wake at 03:00 or 23:00 does the same work as the old fixed-time jobs:
  - media window: once a day, put the coming month's Reels in git and push, so the cloud poster never waits for the Mac
  - weekly report: once every 7 days (the Supabase CLI login and the credit ledger live here)
Production is not here: com.arthvan.production-resume already retries it every 10 minutes while the Mac is on.
python -m engine.catchup            run what is due
python -m engine.catchup --dry      say what is due, do nothing"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

STATE = Path.home() / "arthvan-social" / "logs" / "catchup.json"
WEEKLY_EVERY_DAYS = 7


def load_state(path: Path = STATE) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict, path: Path = STATE) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def _day(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def due(state: dict, today: date) -> list:
    """Which duties are owed today, in the order they run."""
    out = []
    if _day(state.get("window")) != today:
        out.append("window")
    last = _day(state.get("weekly"))
    if last is None or (today - last).days >= WEEKLY_EVERY_DAYS:
        out.append("weekly")
    return out


def run(today: date | None = None, state_path: Path = STATE, window=None, weekly=None, dry: bool = False) -> list:
    """Runs the due duties; a duty is marked done only when it returns 0, so a failed push is retried on the next tick."""
    today = today or (datetime.now(timezone.utc) + timedelta(hours=1)).date()          # Lagos day, like the rest of the engine
    state = load_state(state_path)
    owed = due(state, today)
    if dry:
        return owed
    done = []
    for duty in owed:
        if duty == "window":
            from . import media_window
            rc = (window or (lambda: media_window.main(["--push"])))()
        else:
            from . import weekly_report
            rc = (weekly or (lambda: weekly_report.main([])))()
        if rc == 0:
            state[duty] = today.isoformat()
            save_state(state, state_path)
            done.append(duty)
        else:
            print(f"catchup: {duty} failed (exit {rc}); will retry on the next tick", flush=True)
    return done


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--dry" in argv:
        print("due now:", ", ".join(run(dry=True)) or "nothing")
        return 0
    done = run()
    print("catchup did:", ", ".join(done) or "nothing (nothing was due, or a duty failed and will retry)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
