import json
from datetime import date, datetime, timezone
from types import SimpleNamespace as R

from engine import backup_trigger as bt

LOG = json.dumps({"date": "2026-10-13", "status": "published", "item": "x"}) + "\n" + json.dumps({"date": "2026-10-14", "channel": "threads", "status": "published"}) + "\n"
NOW = datetime(2026, 10, 14, 17, 10, tzinfo=timezone.utc)      # 18:10 Lagos on 14 Oct


def runner(log, calls):
    def run(cmd, **kw):
        calls.append(cmd)
        return R(returncode=0, stdout=log, stderr="") if cmd[0] == "gh" and cmd[1] == "api" else R(returncode=0, stdout="", stderr="")
    return run


def test_only_an_instagram_publish_for_that_day_counts_as_posted():
    assert bt.posted_today(LOG, date(2026, 10, 13)) and not bt.posted_today(LOG, date(2026, 10, 14))     # a Threads-only entry is not the post


def test_starts_the_workflow_when_today_is_missing_and_stays_quiet_when_it_is_there():
    calls = []
    assert bt.main(runner(LOG, calls), NOW) == 0 and calls[-1][:3] == ["gh", "workflow", "run"] and "mode=post" in calls[-1]
    calls = []
    assert bt.main(runner(LOG, calls), datetime(2026, 10, 13, 17, 10, tzinfo=timezone.utc)) == 0 and len(calls) == 1


def test_if_the_log_cannot_be_read_it_still_starts_the_workflow():
    calls = []
    def run(cmd, **kw):
        calls.append(cmd); return R(returncode=1, stdout="", stderr="offline") if cmd[1] == "api" else R(returncode=0, stdout="", stderr="")
    assert bt.main(run, NOW) == 0 and calls[-1][:3] == ["gh", "workflow", "run"]
