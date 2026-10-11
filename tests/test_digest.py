from datetime import date

from engine import digest
from engine.digest import collect, render_markdown

MEDIA = [
    {"id": "1", "media_product_type": "FEED", "media_type": "CAROUSEL_ALBUM", "permalink": "https://ig/p/a",
     "timestamp": "2026-10-10T20:35:00+0000", "caption": "A simple month-end routine...", "like_count": 12, "comments_count": 1},
    {"id": "2", "media_product_type": "REELS", "media_type": "VIDEO", "permalink": "https://ig/reel/b",
     "timestamp": "2026-10-10T20:35:30+0000", "caption": "You made money on paper...", "like_count": 30, "comments_count": 4},
    {"id": "9", "media_product_type": "FEED", "media_type": "IMAGE", "permalink": "https://ig/p/old",
     "timestamp": "2026-09-01T10:00:00+0000", "caption": "old", "like_count": 1, "comments_count": 0},
]
INSIGHTS = {"1": {"reach": 400, "views": 520, "saved": 3, "shares": 2}, "2": {"reach": 1500, "views": 2100, "saved": 8, "shares": 11}}


def fake_call(method, path, token, params=None):
    if path == "/me/media":
        return {"data": MEDIA}
    if path.endswith("/insights"):
        mid = path.strip("/").split("/")[0]
        return {"data": [{"name": k, "values": [{"value": v}]} for k, v in INSIGHTS[mid].items()]}
    if path == "/me":
        return {"followers_count": 18010}
    raise AssertionError(path)


def test_collect_keeps_only_the_last_seven_days_and_attaches_insights(monkeypatch):
    monkeypatch.setattr(digest, "call", fake_call)
    rep = collect("tok", date(2026, 10, 12))
    assert [m["id"] for m in rep["media"]] == ["1", "2"]
    assert rep["media"][1]["reach"] == 1500 and rep["media"][0]["saved"] == 3
    assert rep["followers"] == 18010


def test_markdown_has_a_table_sorted_by_reach_and_totals():
    rep = {"followers": 18010, "week_end": date(2026, 10, 12), "media": [
        dict(MEDIA[0], **INSIGHTS["1"]), dict(MEDIA[1], **INSIGHTS["2"])]}
    md = render_markdown(rep, {"2026-10-10": {"app": "scoremybiz", "item": "smb-month-end"}})
    lines = md.splitlines()
    assert lines[0].startswith("# Weekly report")
    first_row = next(l for l in lines if l.startswith("| 2026-10-10"))
    assert "Reel" in first_row and "1,500" in first_row  # highest reach first
    assert "Total reach: 1,900" in md and "Followers: 18,010" in md
    assert "smb-month-end" in md and "scoremybiz" in md


def test_insight_failure_for_one_post_does_not_break_the_report(monkeypatch):
    def flaky(method, path, token, params=None):
        if path.startswith("/2/insights"):
            raise digest.InstagramError("no insights for this media")
        return fake_call(method, path, token, params)
    monkeypatch.setattr(digest, "call", flaky)
    rep = collect("tok", date(2026, 10, 12))
    assert rep["media"][1]["reach"] is None and rep["media"][0]["reach"] == 400
