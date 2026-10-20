import json
from datetime import date
from types import SimpleNamespace as R

from engine import media_window as mw

TODAY = date(2026, 10, 14)


def setup(tmp_path, sched, on_disk, tracked):
    (tmp_path / "content").mkdir(); (tmp_path / "stories" / "out").mkdir(parents=True)
    (tmp_path / "content" / "schedule.json").write_text(json.dumps(sched))
    for i in on_disk: (tmp_path / "stories" / "out" / f"{i}.mp4").write_bytes(b"x")
    return lambda cmd, **kw: R(returncode=0, stdout="\n".join(f"stories/out/{t}.mp4" for t in tracked) if "ls-files" in cmd else "", stderr="")


def test_the_window_runs_from_three_days_back_to_a_month_ahead():
    s = {"2026-10-10": "old", "2026-10-11": "back", "2026-10-14": "today", "2026-11-14": "edge", "2026-11-15": "far"}
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp()); (d / "content").mkdir(); (d / "content" / "schedule.json").write_text(json.dumps(s))
    assert mw.wanted_ids(d, TODAY) == {"back", "today", "edge"}


def test_reels_outside_the_window_leave_github_but_stay_on_disk_and_missing_ones_are_reported(tmp_path):
    run = setup(tmp_path, {"2026-10-14": "a", "2026-10-15": "b", "2026-10-16": "ghost"}, on_disk=["a", "b", "c"], tracked=["a", "c"])
    p = mw.plan(tmp_path, TODAY, run)
    assert p["add"] == ["stories/out/a.mp4", "stories/out/b.mp4"] and p["drop"] == ["stories/out/c.mp4"] and p["missing"] == ["ghost"]
    assert (tmp_path / "stories" / "out" / "c.mp4").exists()                 # planning never touches files


def test_apply_force_adds_window_files_untracks_the_rest_and_commits_once(tmp_path):
    calls = []
    base = setup(tmp_path, {"2026-10-14": "a"}, on_disk=["a", "c"], tracked=["c"])
    def run(cmd, **kw):
        calls.append(cmd[3:]); return R(returncode=1 if "diff" in cmd else 0, stdout=base(cmd).stdout, stderr="")   # diff --cached --quiet -> 1 = there are staged changes
    p = mw.apply(tmp_path, TODAY, run)
    assert ["add", "-f", "stories/out/a.mp4"] in calls and ["rm", "--cached", "-q", "stories/out/c.mp4"] in calls
    assert sum(1 for c in calls if c[0] == "commit") == 1 and p["committed"]
    assert (tmp_path / "stories" / "out" / "c.mp4").exists()                 # the file stays on the Mac


def test_nothing_changes_when_the_repo_already_matches_the_window(tmp_path):
    base = setup(tmp_path, {"2026-10-14": "a"}, on_disk=["a"], tracked=["a"])
    calls = []
    def run(cmd, **kw): calls.append(cmd[3:]); return R(returncode=0, stdout=base(cmd).stdout, stderr="")
    p = mw.apply(tmp_path, TODAY, run)
    assert not any(c[0] == "commit" for c in calls) and "committed" not in p
