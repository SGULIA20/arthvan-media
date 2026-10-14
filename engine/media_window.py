"""Keeps GitHub light. The Mac is the library for every finished Reel (stories/out/*.mp4 on disk, never deleted); the repository
carries only the Reels the cloud run can need soon: those scheduled from 3 days ago (for retries) to 10 days ahead.
Everything outside that window is UNTRACKED (git rm --cached), so the file stays on the Mac and leaves GitHub's current files.
python -m engine.media_window            show what would change
python -m engine.media_window --apply    stage the changes and commit them
python -m engine.media_window --push     apply, then push through ~/arthvan-social/bin/push-arthvan-media.sh"""
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAYS_BACK, DAYS_AHEAD = 3, 10
PUSH_SCRIPT = Path.home() / "arthvan-social" / "bin" / "push-arthvan-media.sh"


def wanted_ids(root: Path, today: date) -> set:
    sched = json.loads((Path(root) / "content" / "schedule.json").read_text()) if (Path(root) / "content" / "schedule.json").exists() else {}
    lo, hi = (today - timedelta(days=DAYS_BACK)).isoformat(), (today + timedelta(days=DAYS_AHEAD)).isoformat()
    return {sid for d, sid in sched.items() if lo <= d <= hi and sid}


def _git(root: Path, *args, run=subprocess.run):
    return run(["git", "-C", str(root), *args], capture_output=True, text=True)


def plan(root: Path, today: date, run=subprocess.run) -> dict:
    root = Path(root)
    want = wanted_ids(root, today)
    tracked = [l for l in _git(root, "ls-files", "stories/out", run=run).stdout.splitlines() if l.endswith(".mp4")]
    tracked_ids = {Path(t).stem for t in tracked}
    add = sorted(f"stories/out/{i}.mp4" for i in want if (root / "stories" / "out" / f"{i}.mp4").exists())
    drop = sorted(t for t in tracked if Path(t).stem not in want)
    missing = sorted(i for i in want if not (root / "stories" / "out" / f"{i}.mp4").exists())
    return {"add": add, "drop": drop, "missing": missing, "already": sorted(i for i in want if i in tracked_ids)}


def apply(root: Path, today: date, run=subprocess.run) -> dict:
    p = plan(root, today, run)
    for f in p["add"]:
        _git(root, "add", "-f", f, run=run)                    # -f: the folder is ignored, the window files are the exception
    for f in p["drop"]:
        _git(root, "rm", "--cached", "-q", f, run=run)         # leaves the file on the Mac
    if _git(root, "diff", "--cached", "--quiet", run=run).returncode != 0:
        _git(root, "commit", "-m", f"media window {today}: {len(p['add'])} Reels on GitHub, {len(p['drop'])} left the repo (still on the Mac)", run=run)
        p["committed"] = True
    return p


def main(argv=None, run=subprocess.run) -> int:
    argv = sys.argv[1:] if argv is None else argv
    today = (datetime.now(timezone.utc) + timedelta(hours=1)).date()
    if "--apply" not in argv and "--push" not in argv:
        p = plan(ROOT, today, run)
    else:
        p = apply(ROOT, today, run)
    print(f"window {today - timedelta(days=DAYS_BACK)} to {today + timedelta(days=DAYS_AHEAD)}: keep/add {len(p['add'])}, leave GitHub {len(p['drop'])}")
    for f in p["drop"]:
        print("  leaves GitHub (stays on the Mac):", f)
    for i in p["missing"]:
        print("  WARNING scheduled but no video on this Mac:", i)
    if "--push" in argv:
        return run([str(PUSH_SCRIPT)]).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
