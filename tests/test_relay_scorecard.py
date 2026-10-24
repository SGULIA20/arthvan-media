from datetime import date, datetime, timezone

from engine import relay_scorecard as rs


def test_the_relay_asks_for_the_same_lagos_day_the_card_is_dated():
    # the relay runs at 21:28 WAT, which is already 01:58 on the next day in India: it used to ask for that day and always said "not available"
    assert rs.report_day(datetime(2026, 10, 22, 20, 28, tzinfo=timezone.utc)).isoformat() == "2026-10-22"
    assert rs.report_day(datetime(2026, 10, 24, 23, 30, tzinfo=timezone.utc)).isoformat() == "2026-10-24"    # 00:30 WAT, a late run: the day that ended
    assert rs.report_day(datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)).isoformat() == "2026-10-25"      # 05:00 WAT: a new day


def test_todays_card_is_relayed_as_is():
    card = "📋 Evening status Thu 22 Oct 2026 — all posted ✅\n\nScoreMyBiz Reel\n   YouTube: ✅ Posted"
    assert rs.message(card, date(2026, 10, 22)) == card


def test_stale_or_missing_card_says_so():
    assert "not available" in rs.message("📋 Evening status Wed 21 Oct 2026 — all posted ✅", date(2026, 10, 22))
    assert "not available" in rs.message("", date(2026, 10, 22))
