import json
from datetime import date

from engine import claims

FEATS = {"waypoint": {"write-post": {"status": "live"}, "calm-kit": {"status": "gated", "gate": "Android v25"},
                      "daily-news": {"status": "partial", "gate": "not daily"}, "overview": {"status": "general"}}}
SMAP = {"waypoint": {"create_typed.png": "write-post", "calm.png": "calm-kit", "explore.png": "daily-news"}}


def story(feature="write-post", screens=("create_typed.png",), **kw):
    d = {"id": "s", "app": "waypoint", "feature": feature, "scenes": [{"screen": s} for s in screens]}; d.update(kw); return d


def test_a_live_story_has_no_problems():
    assert claims.story_problems(story(), FEATS, SMAP) == []


def test_gated_and_partial_features_block_a_story_by_feature_or_by_screen():
    assert "gated" in claims.story_problems(story(feature="calm-kit"), FEATS, SMAP)[0]
    p = claims.story_problems(story(screens=("create_typed.png", "calm.png", "explore.png")), FEATS, SMAP)
    assert any("scene 1" in x and "gated" in x for x in p) and any("scene 2" in x and "partial" in x for x in p)


def test_an_unknown_screen_or_feature_fails_closed_when_the_app_has_a_catalogue():
    assert claims.story_problems(story(screens=("mystery.png",)), FEATS, SMAP)
    assert claims.story_problems(story(feature="made-up"), FEATS, SMAP)


def test_an_app_without_a_catalogue_is_not_blocked_and_a_hold_always_blocks():
    assert claims.story_problems({"id": "s", "app": "scoremybiz", "feature": "x", "scenes": [{"screen": "a.png"}]}, FEATS, SMAP) == []
    assert "on hold" in claims.story_problems(story(hold="wording to fix"), FEATS, SMAP)[0]


def test_bank_items_with_gated_features_are_blocked_and_general_tags_pass():
    assert claims.item_problems("waypoint", {"feature": "calm-kit"}, FEATS)
    assert claims.item_problems("waypoint", {"feature": "overview"}, FEATS) == []
    assert claims.item_problems("waypoint", {"feature": "write-post", "hold": "x"}, FEATS)


def test_the_planner_never_plans_a_story_with_claim_problems(tmp_path):
    from engine import calendar_plan as cp
    from engine.run_daily import scheduled_story
    (tmp_path / "stories" / "out").mkdir(parents=True); (tmp_path / "content").mkdir()
    (tmp_path / "content" / "features.json").write_text(json.dumps(FEATS)); (tmp_path / "content" / "screen_features.json").write_text(json.dumps(SMAP))
    for sid, shot in (("good", "create_typed.png"), ("bad", "calm.png")):
        (tmp_path / "stories" / f"{sid}.json").write_text(json.dumps({"id": sid, "app": "waypoint", "character": "mira", "feature": "write-post", "post_on": "2026-10-01",
                                                                    "scenes": [{"screen": shot}]}))
        (tmp_path / "stories" / "out" / f"{sid}.mp4").write_bytes(b"v")
    stories = cp.load_stories(tmp_path)
    assert {s["id"]: bool(s["problems"]) for s in stories} == {"good": False, "bad": True}
    plan = cp.build_plan(date(2026, 10, 17), 1, stories)                 # 17 Oct is a Waypoint + female day
    assert plan["2026-10-17"] == "good"
    (tmp_path / "content" / "schedule.json").write_text(json.dumps({"2026-10-17": "bad"}))
    assert scheduled_story(tmp_path, date(2026, 10, 17), tmp_path / "none.jsonl") is None            # even a stale schedule cannot post it
