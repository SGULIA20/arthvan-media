"""Backup for GitHub's scheduler, which has fired hours late or not at all (12 and 13 Oct 2026).
Run from a Mac launch agent (com.arthvan.postbackup) at 15:45 and 16:45 Lagos = about 20:15 India (moved from 18:10 on 18 Oct 2026, because 87% of the audience is in India): if today's Instagram post is not in the repo's log, start the daily-post workflow.
The engine itself never posts twice on one day, and the workflow has a concurrency group, so a late scheduler run is harmless."""
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

REPO = "SGULIA20/arthvan-media"


def posted_today(log_text: str, day: date) -> bool:
    for line in log_text.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("date") == day.isoformat() and e.get("status") == "published" and e.get("channel", "instagram") == "instagram":
            return True
    return False


def main(run=subprocess.run, now=None) -> int:
    day = ((now or datetime.now(timezone.utc)) + timedelta(hours=1)).date()
    got = run(["gh", "api", f"repos/{REPO}/contents/logs/posts.jsonl", "-H", "Accept: application/vnd.github.raw"], capture_output=True, text=True)
    if got.returncode != 0:
        print(f"backup trigger: could not read the post log ({got.stderr.strip()[:150]}); starting the workflow to be safe")
    elif posted_today(got.stdout, day):
        print(f"{day}: already posted, nothing to do")
        return 0
    started = run(["gh", "workflow", "run", "daily-post.yml", "-R", REPO, "-f", "mode=post"], capture_output=True, text=True)
    print("daily-post started" if started.returncode == 0 else f"could not start daily-post: {started.stderr.strip()[:200]}")
    return started.returncode


if __name__ == "__main__":
    sys.exit(main())
