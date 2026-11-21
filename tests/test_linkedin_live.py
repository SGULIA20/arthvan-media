"""The fact gate for the two live LinkedIn categories (founder, 21 Nov 2026: 'Auto, with a fact gate')."""
import json
from datetime import date

from engine import linkedin_live as live

SETTINGS = {"base_hashtags": ["#SGLearning"], "min_hashtags": 3, "max_hashtags": 5, "banned_phrases": ["guarantee"], "already_posted": ["Kodak"]}
URLS = {"https://www.reuters.com/markets/gold-1", "https://www.ft.com/content/gold-2", "https://www.reuters.com/markets/gold-3"}
DAY = date(2026, 11, 24)


def post(**over):
    body = ("Gold fell 4 percent in the week to 20 November, its sharpest weekly drop since June. The move came as the dollar rose and "
            "traders cut bets on a rate cut. " + "Importers who price in dollars feel it first and treasurers who hedged late feel it most. " * 3 +
            "A falling price is not a signal by itself. The lesson for a finance head is to set the hedge policy before the move, not after. "
            "My view is that most plants decide this in the wrong month.")
    p = {"id": "gold-week", "hook": "Gold fell 4 percent in a week. The reason was not gold.", "body": body,
         "question": "When did your hedge policy last change before a move, not after it?", "hashtags": ["#Gold", "#Treasury"],
         "card": {"title": "Gold fell 4 percent in a week", "points": ["Dollar up", "Rate-cut bets down"], "source": "Reuters, FT"},
         "scene": "gold bars on a vault shelf", "as_of": "2026-11-20",
         "claims": [{"claim": "Gold fell 4 percent in the week to 20 November 2026, its sharpest weekly drop since June",
                     "sources": ["https://www.reuters.com/markets/gold-1", "https://www.ft.com/content/gold-2"]}]}
    p.update(over)
    return p


def test_a_sound_post_passes_the_gate_and_becomes_a_lane_item():
    assert live.gate(post(), URLS, "markets", DAY, SETTINGS) == []
    item = live.to_item(post(), "markets")
    assert item["id"] == "live-gold-week" and item["pillar"] == "markets" and "reuters.com" in item["facts"] and len(item["sources"]) == 2


def test_the_gate_stops_invented_links_single_sources_loose_numbers_and_stale_market_figures():
    bad_link = post(claims=[{"claim": "Gold fell 4 percent in the week to 20 November 2026 since June", "sources": ["https://www.reuters.com/markets/gold-1", "https://made-up.example/x"]}])
    assert any("did not return" in p for p in live.gate(bad_link, URLS, "markets", DAY, SETTINGS))
    one_site = post(claims=[{"claim": "Gold fell 4 percent in the week to 20 November 2026 since June", "sources": ["https://www.reuters.com/markets/gold-1", "https://www.reuters.com/markets/gold-3"]}])
    assert any("fewer than two sites" in p for p in live.gate(one_site, URLS, "markets", DAY, SETTINGS))
    loose = post(hook="Gold fell 4 percent in a week and 9 percent this quarter.")
    assert any("no claim covers: 9" in p for p in live.gate(loose, URLS, "markets", DAY, SETTINGS))
    assert any("not within" in p for p in live.gate(post(as_of="2026-11-10"), URLS, "markets", DAY, SETTINGS))
    assert any("not within" in p for p in live.gate(post(as_of="soon"), URLS, "markets", DAY, SETTINGS))
    assert live.gate(post(as_of="2026-11-10"), URLS, "news", DAY, SETTINGS) == []          # only market prices must be days old
    assert any("words" in p for p in live.gate(post(body="Gold fell 4 percent. Too short."), URLS, "markets", DAY, SETTINGS))
    assert any("no claims" in p for p in live.gate(post(claims=[]), URLS, "markets", DAY, SETTINGS))


def test_write_uses_the_post_only_when_the_second_check_confirms_every_claim(tmp_path):
    (tmp_path / "content" / "prompts").mkdir(parents=True)
    (tmp_path / "content" / "prompts" / "linkedin-brief.md").write_text("brief")
    def asker(verdict):
        calls = []
        def ask(messages, system):
            calls.append(messages[0]["content"])
            if len(calls) == 1:
                return {"text": "Here it is:\n" + json.dumps(post()), "urls": URLS}
            return {"text": json.dumps(verdict), "urls": set()}
        ask.calls = calls
        return ask
    ok = asker({"claims": [{"n": 1, "true": True, "note": "confirmed"}], "hook_supported": True})
    item, why = live.write("markets", DAY, ["An older hook"], SETTINGS, root=tmp_path, ask=ok)
    assert item and item["id"] == "live-gold-week" and why == "" and "An older hook" in ok.calls[0] and "Check each claim" in ok.calls[1]
    item, why = live.write("markets", DAY, [], SETTINGS, root=tmp_path, ask=asker({"claims": [{"n": 1, "true": False, "note": "it fell 2 percent"}], "hook_supported": True}))
    assert item is None and "it fell 2 percent" in why
    item, why = live.write("markets", DAY, [], SETTINGS, root=tmp_path, ask=asker({"claims": [], "hook_supported": True}))
    assert item is None and "second check" in why                                          # a claim left unchecked is not a pass
    def broken(messages, system):
        raise live.LiveError("Claude failed (529)")
    item, why = live.write("markets", DAY, [], SETTINGS, root=tmp_path, ask=broken)
    assert item is None and "529" in why                                                   # never raises: the bank post goes out
