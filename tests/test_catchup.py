from datetime import date

from engine import catchup


def test_everything_is_due_on_a_fresh_mac():
    assert catchup.due({}, date(2026, 10, 21)) == ["window", "weekly"]


def test_window_is_daily_and_weekly_every_seven_days():
    s = {"window": "2026-10-21", "weekly": "2026-10-17"}
    assert catchup.due(s, date(2026, 10, 21)) == []
    assert catchup.due(s, date(2026, 10, 22)) == ["window"]
    assert catchup.due(s, date(2026, 10, 24)) == ["window", "weekly"]


def test_run_marks_only_successful_duties_and_retries_failures(tmp_path):
    state = tmp_path / "catchup.json"
    calls = []
    done = catchup.run(date(2026, 10, 21), state, window=lambda: calls.append("w") or 0, weekly=lambda: calls.append("r") or 1)
    assert done == ["window"] and calls == ["w", "r"]
    assert catchup.load_state(state) == {"window": "2026-10-21"}
    done = catchup.run(date(2026, 10, 21), state, window=lambda: calls.append("w") or 0, weekly=lambda: calls.append("r") or 0)
    assert done == ["weekly"] and calls == ["w", "r", "r"]                      # the window is not redone the same day
    assert catchup.load_state(state) == {"window": "2026-10-21", "weekly": "2026-10-21"}


def test_dry_run_changes_nothing(tmp_path):
    state = tmp_path / "s.json"
    assert catchup.run(date(2026, 10, 21), state, dry=True) == ["window", "weekly"]
    assert not state.exists()


def test_bad_state_file_is_treated_as_empty(tmp_path):
    p = tmp_path / "s.json"; p.write_text("{not json")
    assert catchup.load_state(p) == {}
