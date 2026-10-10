from engine.config import load_apps, load_bank, validate_item

GOOD = {
    "id": "x1",
    "template": "ink",
    "caption": "A short caption.",
    "hashtags": ["#One"],
    "slides": [
        {"kind": "hook", "text": "Hello"},
        {"kind": "steps", "text": "Three things", "items": ["a", "b", "c"]},
        {"kind": "quote", "text": "Bye"},
    ],
}


def test_load_apps_has_both_apps_with_play_urls():
    apps = load_apps()
    assert set(apps) == {"waypoint", "scoremybiz"}
    assert apps["scoremybiz"]["play_url"] == "https://play.google.com/store/apps/details?id=com.scoremybiz.app"
    assert apps["waypoint"]["play_url"] == "https://play.google.com/store/apps/details?id=com.arthvananalytics.waypoint"


def test_validate_item_accepts_a_good_item():
    assert validate_item(GOOD) == []


def test_validate_item_flags_missing_slides():
    bad = {k: v for k, v in GOOD.items() if k != "slides"}
    problems = validate_item(bad)
    assert any("slides" in p for p in problems)


def test_validate_item_flags_unknown_kind_and_template():
    bad = dict(GOOD, template="neon", slides=[{"kind": "banner", "text": "x"}] * 3)
    problems = validate_item(bad)
    assert any("template" in p for p in problems)
    assert any("kind" in p for p in problems)


def test_validate_item_requires_three_to_six_slides():
    assert any("slides" in p for p in validate_item(dict(GOOD, slides=GOOD["slides"][:2])))
    assert any("slides" in p for p in validate_item(dict(GOOD, slides=GOOD["slides"] * 3)))


def test_load_bank_returns_a_list_for_each_app():
    for app in ("waypoint", "scoremybiz"):
        assert isinstance(load_bank(app), list)
