from datetime import date, datetime, timezone

import pytest

from engine.select_item import lagos_date, pick

BANKS = {
    "waypoint": [{"id": f"w{i}"} for i in range(3)],
    "scoremybiz": [{"id": f"s{i}"} for i in range(3)],
}


def test_apps_alternate_starting_with_waypoint_on_epoch():
    assert pick(date(2026, 10, 11), BANKS).app == "waypoint"
    assert pick(date(2026, 10, 12), BANKS).app == "scoremybiz"
    assert pick(date(2026, 10, 13), BANKS).app == "waypoint"


def test_same_input_gives_same_output():
    assert pick(date(2026, 10, 20), BANKS) == pick(date(2026, 10, 20), BANKS)


def test_each_app_advances_one_item_every_two_days_and_wraps():
    ids = [pick(date(2026, 10, 11 + 2 * k), BANKS).item["id"] for k in range(4)]
    assert ids == ["w0", "w1", "w2", "w0"]


def test_skip_moves_to_the_next_item_of_the_same_app():
    base = pick(date(2026, 10, 11), BANKS)
    nxt = pick(date(2026, 10, 11), BANKS, skip=1)
    assert nxt.app == base.app and nxt.item["id"] == "w1"


def test_lagos_date_uses_utc_plus_one():
    assert lagos_date(datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)) == date(2026, 10, 11)
    assert lagos_date(datetime(2026, 10, 11, 23, 30, tzinfo=timezone.utc)) == date(2026, 10, 12)


def test_empty_bank_raises():
    with pytest.raises(ValueError):
        pick(date(2026, 10, 11), {"waypoint": [], "scoremybiz": BANKS["scoremybiz"]})
