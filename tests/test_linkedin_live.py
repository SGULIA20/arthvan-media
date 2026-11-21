"""The fact gate for the two live LinkedIn categories (founder, 21 Nov 2026: 'Auto, with a fact gate')."""
import json
from datetime import date

from engine import linkedin_live as live

SETTINGS = {"base_hashtags": ["#SGLearning"], "min_hashtags": 3, "max_hashtags": 5, "banned_phrases": ["guarantee"], "already_posted": ["Kodak"]}
URLS = {"https://www.reuters.com/markets/gold-1", "https://www.ft.com/content/gold-2", "https://www.reuters.com/markets/gold-3"}
DAY = date(2026, 11, 24)
GOOD = {"sources_credible": True, "expectations_clear": True, "causes_supported": True, "three_parts": True}


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
        def ask(messages, system, searches=8):
            calls.append(messages[0]["content"])
            if len(calls) == 1:
                return {"text": "Here it is:\n" + json.dumps(post()), "urls": URLS}
            return {"text": json.dumps(verdict), "urls": set()}
        ask.calls = calls
        return ask
    ok = asker({"claims": [{"n": 1, "true": True, "note": "confirmed"}], "hook_supported": True, **GOOD})
    item, why = live.write("markets", DAY, ["An older hook"], SETTINGS, root=tmp_path, ask=ok)
    assert item and item["id"] == "live-gold-week" and why == "" and "An older hook" in ok.calls[0] and "Check each claim" in ok.calls[1]
    item, why = live.write("markets", DAY, [], SETTINGS, root=tmp_path, ask=asker({"claims": [{"n": 1, "true": False, "note": "it fell 2 percent"}], "hook_supported": True, **GOOD}))
    assert item is None and "it fell 2 percent" in why
    item, why = live.write("markets", DAY, [], SETTINGS, root=tmp_path, ask=asker({"claims": [], "hook_supported": True, **GOOD}))
    assert item is None and "second check" in why                                          # a claim left unchecked is not a pass
    def broken(messages, system, searches=8):
        raise live.LiveError("Claude failed (529)")
    item, why = live.write("markets", DAY, [], SETTINGS, root=tmp_path, ask=broken)
    assert item is None and "529" in why                                                   # never raises: the bank post goes out


def test_a_post_that_fails_the_gate_gets_one_chance_to_be_mended(tmp_path):
    """21 Nov 2026, the first real run: one claim had a single site and the year 2027 was in no claim."""
    (tmp_path / "content" / "prompts").mkdir(parents=True)
    (tmp_path / "content" / "prompts" / "linkedin-brief.md").write_text("brief")
    flawed = post(hook="Gold fell 4 percent in a week. Cuts may wait until 2027.")
    verdict = {"claims": [{"n": 1, "true": True, "note": "ok"}], "hook_supported": True, **GOOD}
    def run(second):
        calls = []
        def ask(messages, system, searches=8):
            calls.append(messages)
            return [{"text": json.dumps(flawed), "urls": URLS}, {"text": json.dumps(second), "urls": {"https://www.wsj.com/x"}},
                    {"text": json.dumps(verdict), "urls": set()}][len(calls) - 1]
        return live.write("markets", DAY, [], SETTINGS, root=tmp_path, ask=ask), calls
    (item, why), calls = run(post())
    assert item and why == "" and len(calls) == 3
    assert "no claim covers: 2027" in calls[1][2]["content"] and calls[1][1]["role"] == "assistant"      # told exactly what failed
    (item, why), calls = run(flawed)
    assert item is None and "2027" in why and len(calls) == 2                                            # still flawed: no third try, no check


def test_two_pages_of_one_site_count_once_even_on_two_part_country_domains():
    assert live._site("https://www.bbc.co.uk/news/1") == "bbc.co.uk" and live._site("https://www.ft.co.uk/x") == "ft.co.uk"
    assert live._site("https://economictimes.indiatimes.com/a") == "indiatimes.com" and live._site("https://www.rbi.org.in/x") == "rbi.org.in"


def test_the_second_check_gets_more_searches_and_a_post_rests_on_few_claims(tmp_path):
    """21 Nov 2026: the second check ran out of searches before it had confirmed every claim."""
    (tmp_path / "content" / "prompts").mkdir(parents=True)
    (tmp_path / "content" / "prompts" / "linkedin-brief.md").write_text("brief")
    seen = []
    def ask(messages, system, searches=8):
        seen.append(searches)
        return {"text": json.dumps(post()), "urls": URLS} if len(seen) == 1 else {"text": json.dumps({"claims": [{"n": 1, "true": True}], "hook_supported": True, **GOOD}), "urls": set()}
    item, _why = live.write("markets", DAY, [], SETTINGS, root=tmp_path, ask=ask)
    assert item and seen == [8, live.CHECK_SEARCHES] and live.CHECK_SEARCHES >= 2 * live.MAX_CLAIMS
    many = post(claims=[post()["claims"][0]] * 6)
    assert any("6 claims" in p for p in live.gate(many, URLS, "markets", DAY, SETTINGS))
    assert "At most 5 claims" in live.write_prompt("markets", DAY, []) and "never leave a claim unchecked" in live.verify_prompt(post(), DAY)


def test_the_second_check_also_stops_expectations_as_decisions_unproven_causes_and_a_post_without_a_lesson(tmp_path):
    """Founder, 21 Nov 2026, after the first sample: three rules of accuracy and the three things every post connects."""
    (tmp_path / "content" / "prompts").mkdir(parents=True)
    (tmp_path / "content" / "prompts" / "linkedin-brief.md").write_text("brief")
    def run(**flags):
        n = []
        def ask(messages, system, searches=8):
            n.append(messages[0]["content"])
            return {"text": json.dumps(post()), "urls": URLS} if len(n) == 1 else \
                {"text": json.dumps({"claims": [{"n": 1, "true": True}], "hook_supported": True, **GOOD, **flags, "note": "futures only"}), "urls": set()}
        return live.write("markets", DAY, [], SETTINGS, root=tmp_path, ask=ask), n
    (item, why), n = run()
    assert item and "futures price in" in n[0] and "WHAT HAPPENED" in n[0] and "expectations_clear" in n[1] and "Post: Gold fell" in n[1]
    (item, why), _ = run(expectations_clear=False)
    assert item is None and "an expectation worded as a decision" in why and "futures only" in why
    (item, why), _ = run(causes_supported=False, three_parts=False)
    assert item is None and "a cause stated without evidence" in why and "what a leader should do" in why
    (item, why), _ = run(sources_credible=None)
    assert item is None and "credible source" in why                                       # a missing answer is not a pass


def test_a_data_visual_is_used_only_with_verified_figures_and_the_prompt_spells_them_out():
    from engine import linkedin_personal as lp
    chart = {"format": "chart", "chart": "bar", "why": "the fall is the story", "title": "Gold: a 4 percent week",
             "data": [{"label": "Week to 20 Nov", "value": 4, "unit": "% fall"}, {"label": "June", "value": 4, "unit": "% fall"}],
             "period": "weekly moves, 2026", "source": "Reuters", "highlight": "Week to 20 Nov"}
    assert live.gate(post(visual=chart), URLS, "markets", DAY, SETTINGS) == []
    loose = {**chart, "data": [{"label": "A", "value": 4, "unit": "%"}, {"label": "B", "value": 11, "unit": "%"}]}
    assert any("no claim covers: 11" in p for p in live.gate(post(visual=loose), URLS, "markets", DAY, SETTINGS))      # no invented value
    assert any("at least two" in p for p in live.gate(post(visual={**chart, "data": chart["data"][:1]}), URLS, "markets", DAY, SETTINGS))
    assert any("period and its source" in p for p in live.gate(post(visual={**chart, "source": ""}), URLS, "markets", DAY, SETTINGS))
    donut = {**chart, "chart": "donut", "data": [{"label": "A", "value": 4}, {"label": "B", "value": 4}]}
    assert any("not 100" in p for p in live.gate(post(visual=donut), URLS, "markets", DAY, SETTINGS))
    item = live.to_item(post(visual=chart), "markets")
    prompt, note = lp.image_prompt(item), lp.visual_note(item)
    assert "a bar chart" in prompt and "Week to 20 Nov: 4 % fall" in prompt and "do not round, add or change" in prompt and "Source: Reuters" in prompt
    assert "check every figure" in note and "the fall is the story" in note
    photo = live.to_item(post(), "markets")
    assert "Photorealistic editorial business photograph" in lp.image_prompt(photo) and "editorial photograph" in lp.visual_note(photo)

