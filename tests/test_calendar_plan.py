import json
from datetime import date

from engine import calendar_plan as cp


def S(id, app, character, feature, post_on="2026-10-01", **kw):
    d = {"id": id, "app": app, "character": character, "feature": feature, "post_on": post_on, "rendered": True}; d.update(kw); return d


STORIES = [
    S("old-wp-f", "waypoint", "mira", "create", legacy=True),
    S("old-smb-f", "scoremybiz", "lumi", "payables", legacy=True),
    S("old-wp-m", "waypoint", "founder_casual", "wall", legacy=True),
    S("old-smb-m", "scoremybiz", "founder_suit", "tasks", legacy=True),
    S("new-smb-f", "scoremybiz", "lumi", "voice-entry"),
    S("new-wp-m", "waypoint", "founder_casual", "polls"),
    S("diwali", "scoremybiz", "lumi", "payables", "2026-11-08", occasion="diwali", legacy=True),
]


def plan(start, days, **kw):
    return cp.build_plan(start, days, STORIES, **kw)


def test_new_reels_come_first_and_earlier_made_ones_are_never_on_consecutive_days():
    p = plan(date(2026, 10, 14), 8)            # 14 Oct SMB-F, 15 WP-M, 16 SMB-M, 17 WP-F, 18 SMB-F, 19 WP-M ...
    assert p["2026-10-14"] == "new-smb-f" and p["2026-10-15"] == "new-wp-m"
    assert cp.violations(p, STORIES) == []
    legacy_days = [d for d, sid in sorted(p.items()) if sid and sid.startswith("old")]
    for a, b in zip(legacy_days, legacy_days[1:]):
        assert (date.fromisoformat(b) - date.fromisoformat(a)).days > 1


def test_a_reel_is_used_once_and_a_day_without_a_fit_is_left_for_the_graphics_set():
    p = plan(date(2026, 10, 14), 16)
    used = [sid for sid in p.values() if sid]
    assert len(used) == len(set(used))
    assert None in p.values()


def test_a_festival_reel_wins_its_date_and_shields_its_feature_and_neighbours():
    p = plan(date(2026, 11, 5), 6)
    assert p["2026-11-08"] == "diwali"
    assert p["2026-11-07"] != "old-smb-f" and p["2026-11-09"] != "old-smb-f"      # no earlier-made Reel next to it, none with its feature


def test_pinned_days_keep_their_reel_and_published_reels_are_not_planned_again():
    p = plan(date(2026, 10, 14), 4, keep={"2026-10-14": "old-smb-f"}, published={"old-wp-f": "2026-10-13"})
    assert p["2026-10-14"] == "old-smb-f"
    assert "old-wp-f" not in p.values()


def test_a_feature_shown_in_the_last_ten_days_is_not_repeated():
    p = plan(date(2026, 10, 14), 1, feature_log=[("2026-10-10", "scoremybiz", "voice-entry")])
    assert p["2026-10-14"] != "new-smb-f"


def test_scheduler_follows_the_schedule_file_and_graphics_days_have_no_reel(tmp_path):
    from engine.run_daily import scheduled_story
    (tmp_path / "stories" / "out").mkdir(parents=True); (tmp_path / "content").mkdir()
    for sid, feat in (("a", "x"), ("b", "y")):
        (tmp_path / "stories" / f"{sid}.json").write_text(json.dumps({"id": sid, "app": "waypoint", "character": "mira", "feature": feat, "post_on": "2026-10-01"}))
        (tmp_path / "stories" / "out" / f"{sid}.mp4").write_bytes(b"v")
    (tmp_path / "content" / "schedule.json").write_text(json.dumps({"2026-10-15": "a", "2026-10-18": "b"}))
    log = tmp_path / "posts.jsonl"; log.write_text("")
    assert scheduled_story(tmp_path, date(2026, 10, 14), log) is None            # nothing planned: graphics set
    assert scheduled_story(tmp_path, date(2026, 10, 15), log)["id"] == "a"
    assert scheduled_story(tmp_path, date(2026, 10, 16), log)["id"] == "a"       # a missed Reel still goes out within three days
    log.write_text(json.dumps({"date": "2026-10-15", "app": "waypoint", "item": "a", "status": "published"}) + "\n")
    assert scheduled_story(tmp_path, date(2026, 10, 16), log) is None
    assert scheduled_story(tmp_path, date(2026, 10, 18), log)["id"] == "b"


def test_graphics_posts_avoid_features_of_reels_planned_in_the_next_ten_days(tmp_path):
    (tmp_path / "stories" / "out").mkdir(parents=True); (tmp_path / "content").mkdir()
    (tmp_path / "stories" / "r.json").write_text(json.dumps({"id": "r", "app": "scoremybiz", "character": "lumi", "feature": "voice-entry", "post_on": "2026-10-01"}))
    (tmp_path / "stories" / "out" / "r.mp4").write_bytes(b"v")
    (tmp_path / "content" / "schedule.json").write_text(json.dumps({"2026-10-20": "r"}))
    assert cp.planned_features(tmp_path, "scoremybiz", date(2026, 10, 14)) == ["voice-entry"]
    assert cp.planned_features(tmp_path, "waypoint", date(2026, 10, 14)) == []
    assert cp.planned_features(tmp_path, "scoremybiz", date(2026, 10, 5)) == []       # more than ten days ahead


def test_todays_planned_reel_beats_a_missed_earlier_one(tmp_path):
    from engine.run_daily import scheduled_story
    (tmp_path / "stories" / "out").mkdir(parents=True); (tmp_path / "content").mkdir()
    for sid in ("early", "festival"):
        (tmp_path / "stories" / f"{sid}.json").write_text(json.dumps({"id": sid, "app": "scoremybiz", "character": "lumi", "feature": sid, "post_on": "2026-10-01"}))
        (tmp_path / "stories" / "out" / f"{sid}.mp4").write_bytes(b"v")
    (tmp_path / "content" / "schedule.json").write_text(json.dumps({"2026-10-13": "early", "2026-10-14": "festival"}))
    log = tmp_path / "posts.jsonl"; log.write_text("")
    assert scheduled_story(tmp_path, date(2026, 10, 14), log)["id"] == "festival"     # the festival Reel goes out on its day
    log.write_text(json.dumps({"date": "2026-10-14", "app": "scoremybiz", "item": "festival", "status": "published"}) + "\n")
    assert scheduled_story(tmp_path, date(2026, 10, 15), log)["id"] == "early"          # then the missed one, within three days


def test_a_reel_over_the_60_second_story_limit_is_held_back_and_an_unreadable_one_is_not(tmp_path, monkeypatch):
    for sid in ("long", "ok", "junk"):
        (tmp_path / "stories" / "out").mkdir(parents=True, exist_ok=True)
        (tmp_path / "stories" / f"{sid}.json").write_text(json.dumps({"id": sid, "app": "scoremybiz", "scenes": []}))
        (tmp_path / "stories" / "out" / f"{sid}.mp4").write_bytes(b"x")
    monkeypatch.setattr(cp, "video_seconds", lambda p: {"long": 63.2, "ok": 59.4, "junk": None}[p.stem])
    by_id = {s["id"]: s for s in cp.load_stories(tmp_path)}
    assert by_id["long"]["problems"] == ["video is 63 s, over the 60 s Instagram Story limit"]
    assert by_id["ok"]["problems"] == [] and by_id["junk"]["problems"] == []
