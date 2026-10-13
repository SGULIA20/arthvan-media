import json
from datetime import date

from engine import notify

DAY = date(2026, 10, 13)


def fixture(tmp_path, entries, sched=None, rendered=("a", "b", "c")):
    (tmp_path / "logs").mkdir(parents=True); (tmp_path / "content").mkdir(); (tmp_path / "stories" / "out").mkdir(parents=True)
    (tmp_path / "logs" / "posts.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    (tmp_path / "content" / "schedule.json").write_text(json.dumps(sched or {}))
    for sid, app in (("a", "waypoint"), ("b", "scoremybiz"), ("c", "waypoint"), ("d", "scoremybiz")):
        (tmp_path / "stories" / f"{sid}.json").write_text(json.dumps({"id": sid, "app": app, "scenes": []}))
        if sid in rendered:
            (tmp_path / "stories" / "out" / f"{sid}.mp4").write_bytes(b"x")
    return tmp_path


GOOD = [{"date": "2026-10-13", "item": "x1", "app": "waypoint", "status": "published", "kind": "story"},
        {"date": "2026-10-13", "channel": "threads", "item": "x1", "status": "published", "id": "1"},
        {"date": "2026-10-13", "channel": "youtube:arthvan", "item": "x1", "status": "published", "id": "2"},
        {"date": "2026-10-13", "channel": "linkedin", "item": "x1", "status": "failed", "error": "token expired"},
        {"date": "2026-10-12", "channel": "telegram", "item": "old", "status": "failed", "error": "yesterday"}]


def test_daily_summary_names_what_posted_what_failed_and_what_is_next(tmp_path):
    root = fixture(tmp_path, GOOD, {"2026-10-14": "b", "2026-10-15": "c"})
    t = notify.daily_summary(root, DAY)
    assert "Instagram" in t and "Threads" in t and "YouTube (SG-MYTH-WORLD)" in t and "Waypoint · x1" in t
    assert "Not posted on LinkedIn (failed): token expired" in t and "yesterday" not in t
    assert "14 Oct: ScoreMyBiz · b" in t and "16 Oct: nothing planned" in t


def test_a_later_success_replaces_an_earlier_failure_for_the_same_channel(tmp_path):
    root = fixture(tmp_path, GOOD + [{"date": "2026-10-13", "channel": "linkedin", "item": "x1", "status": "published", "id": "3"}])
    assert "Not posted" not in notify.daily_summary(root, DAY)


def test_buffer_counts_consecutive_finished_days_and_warns_below_seven(tmp_path):
    sched = {f"2026-10-{14 + i}": "abc"[i % 3] for i in range(3)}
    sched["2026-10-18"] = "d"                                     # not rendered, and after a gap anyway
    root = fixture(tmp_path, [], sched)
    assert notify.buffer_days(root, DAY) == (3, date(2026, 10, 16))
    assert notify.buffer_line(root, DAY).startswith("⚠️ Only 3 days of finished Reels ahead")
    sched7 = {f"2026-10-{14 + i}": "abc"[i % 3] for i in range(7)}
    root7 = fixture(tmp_path / "w", [], sched7)
    assert notify.buffer_line(root7, DAY) == "Reels ready ahead: 7 days (through 20 Oct)."


def test_a_reel_with_a_claims_problem_does_not_count_as_ready(tmp_path):
    root = fixture(tmp_path, [], {"2026-10-14": "a"})
    (root / "content" / "features.json").write_text(json.dumps({"waypoint": {"k": {"status": "not_live"}}}))
    (root / "stories" / "a.json").write_text(json.dumps({"id": "a", "app": "waypoint", "feature": "k", "scenes": []}))
    assert notify.buffer_days(root, DAY)[0] == 0


def test_reminders_fire_on_their_date_and_on_a_repeating_schedule(tmp_path):
    root = fixture(tmp_path, [])
    (root / "content" / "reminders.json").write_text(json.dumps([
        {"on": "2026-10-13", "text": "one-off"}, {"on": "2026-10-14", "text": "tomorrow"},
        {"from": "2026-10-06", "every_days": 7, "until": "2026-11-30", "text": "weekly"}]))
    assert notify.reminders_due(root, DAY) == ["one-off", "weekly"]
    assert notify.reminders_due(root, date(2026, 10, 14)) == ["tomorrow"]
    assert notify.reminders_due(root, date(2026, 12, 8)) == []


def test_failure_alert_lists_problem_channels_and_says_when_nothing_was_logged(tmp_path):
    root = fixture(tmp_path, GOOD)
    t = notify.failure_alert(root, DAY, "https://x/run/1")
    assert "LinkedIn: failed (token expired)" in t and "https://x/run/1" in t and "Threads" not in t
    assert "Nothing was logged" in notify.failure_alert(fixture(tmp_path / "e", []), DAY)


def test_after_run_alerts_on_failure_summarises_a_posting_run_and_stays_quiet_when_nothing_happened(tmp_path):
    root = fixture(tmp_path, GOOD)
    sent = []
    send = lambda text, env=None: sent.append(text)
    notify.after_run(root, DAY, 1, 0, env={}, send_fn=send)
    notify.after_run(root, DAY, 0, 0, env={}, send_fn=send)        # entries were added during the run
    notify.after_run(root, DAY, 0, len(GOOD), env={}, send_fn=send)  # the safety-net run found nothing to do
    assert len(sent) == 2 and sent[0].startswith("⚠️ 13 Oct: the daily post needs a look") and sent[1].startswith("⚠️ 13 Oct")


def test_send_never_raises_and_never_leaks_the_token():
    def boom(cfg, text): raise RuntimeError("bad token SECRET123")
    assert notify.send("hi", {"TELEGRAM_BOT_TOKEN": "SECRET123", "TELEGRAM_CHAT_ID": "9"}, sender=boom) is False
    assert notify.send("hi", {"ARTHVAN_ENV": "/nonexistent"}, sender=boom) is False


def test_config_reads_the_mac_env_file_for_telegram_only(tmp_path):
    f = tmp_path / ".env"; f.write_text("OTHER=1\nTELEGRAM_BOT_TOKEN=abc\nTELEGRAM_CHAT_ID='42'\n")
    assert notify.config({"ARTHVAN_ENV": str(f)}) == {"token": "abc", "chat_id": "42"}


def test_the_daily_run_reports_through_notify_only_in_post_mode(monkeypatch, tmp_path):
    from engine import run_daily
    calls, codes = [], iter([0, 1])
    monkeypatch.setattr(run_daily, "run", lambda mode, day: next(codes))
    monkeypatch.setattr(run_daily.notify, "after_run", lambda root, day, code, before: calls.append(code))
    assert run_daily.main(["--mode", "render", "--date", "2026-10-13"]) == 0 and calls == []
    assert run_daily.main(["--mode", "post", "--date", "2026-10-13"]) == 1 and calls == [1]
    def crash(mode, day): raise RuntimeError("boom")
    monkeypatch.setattr(run_daily, "run", crash)
    try:
        run_daily.main(["--mode", "post", "--date", "2026-10-13"])
    except RuntimeError:
        pass
    assert calls == [1, 1]


def test_credit_line_says_how_much_is_left_and_the_daily_pace_to_finish(tmp_path):
    led = tmp_path / "l.json"; led.write_text(json.dumps({"spent_inr": 12000.0}))
    t = notify.credit_line(date(2026, 10, 13), led)
    assert "₹12,000 of ₹28,000 used (43%)" in t and "₹16,000 is left for 58 days" in t and "about ₹276 a day" in t
    led.write_text(json.dumps({"spent_inr": 28000.0}))
    assert notify.credit_line(date(2026, 10, 13), led).startswith("Veo credit is finished")
