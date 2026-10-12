from datetime import date

from engine.select_item import EPOCH, pick


def test_pick_skips_features_the_app_showed_recently_and_falls_back_when_all_are_recent():
    bank = [{"id": f"i{k}", "feature": f} for k, f in enumerate(["cash", "cash", "book", "score", "cash"])]
    banks = {"waypoint": bank, "scoremybiz": bank}
    day = EPOCH                                          # n = 0: starts at index 0
    assert pick(day, banks).item["id"] == "i0"
    assert pick(day, banks, recent_features=["cash"]).item["id"] == "i2"            # the next item with a fresh feature
    assert pick(day, banks, recent_features=["cash", "book"]).item["id"] == "i3"
    assert pick(day, banks, recent_features=["cash", "book", "score"]).item["id"] == "i0"   # everything is recent: plain order
    assert pick(day, banks, skip=1, recent_features=["cash"]).item["id"] == "i3"    # lint skip moves within the fresh ones
