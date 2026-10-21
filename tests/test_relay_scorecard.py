from datetime import date

from engine import relay_scorecard as rs


def test_todays_card_is_relayed_as_is():
    card = "📋 Evening status Thu 22 Oct 2026 — all posted ✅\n\nScoreMyBiz Reel\n   YouTube: ✅ Posted"
    assert rs.message(card, date(2026, 10, 22)) == card


def test_stale_or_missing_card_says_so():
    assert "not available" in rs.message("📋 Evening status Wed 21 Oct 2026 — all posted ✅", date(2026, 10, 22))
    assert "not available" in rs.message("", date(2026, 10, 22))
