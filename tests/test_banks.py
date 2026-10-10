import pytest

from engine.config import load_apps, load_bank, validate_item
from engine.lint import lint_item

APPS = load_apps()


@pytest.mark.parametrize("app", ["waypoint", "scoremybiz"])
def test_bank_is_large_unique_valid_and_lint_clean(app):
    bank = load_bank(app)
    assert len(bank) >= 20
    ids = [i["id"] for i in bank]
    assert len(ids) == len(set(ids))
    for it in bank:
        assert validate_item(it) == [], it["id"]
        assert lint_item(APPS[app], it) == [], it["id"]


@pytest.mark.parametrize("app", ["waypoint", "scoremybiz"])
def test_every_template_and_slide_kind_is_used(app):
    bank = load_bank(app)
    assert {i["template"] for i in bank} == {"ink", "dusk", "spark"}
    kinds = {s["kind"] for i in bank for s in i["slides"]}
    required = {"hook", "stat", "steps", "quote"} | ({"bars"} if app == "scoremybiz" else set())
    assert required <= kinds


@pytest.mark.parametrize("app", ["waypoint", "scoremybiz"])
def test_no_two_items_share_a_headline(app):
    heads = [i["slides"][0]["text"] for i in load_bank(app)]
    assert len(heads) == len(set(heads))
