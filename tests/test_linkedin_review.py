"""LinkedIn, from the topic to the post-mortem (founder, 25 Nov 2026: 'additional steps for LinkedIn as well like we did for YouTube
channels ... You are free to choose any topic worldwide')."""
import json
from datetime import date, datetime, timezone

import pytest

from engine import linkedin_live as live
from engine import linkedin_personal as lp
from engine import linkedin_review as rv
from engine import tg_commands as tg
from tests.test_linkedin_live import DAY, GOOD, SETTINGS, URLS, post


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _root(tmp_path, entries=()):
    (tmp_path / "content" / "prompts").mkdir(parents=True); (tmp_path / "logs").mkdir()
    (tmp_path / "content" / "prompts" / "linkedin-brief.md").write_text("brief")
    bank = {"settings": SETTINGS, "items": [{"id": "amazon-ccc", "pillar": "case", "hook": "Amazon gets paid by customers before it pays suppliers."}]}
    (tmp_path / "content" / "linkedin_personal.json").write_text(json.dumps(bank))
    (tmp_path / "logs" / "posts.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))
    return tmp_path


LOG = [{"date": "2026-11-23", "channel": "linkedin_personal", "item": "amazon-ccc", "status": "published", "format": "founder-picture"},
       {"date": "2026-11-25", "channel": "linkedin_personal", "item": "live-gold-week", "pillar": "trend", "hook": "Gold fell 4 percent in a week. The reason was not gold.", "status": "handed"},
       {"date": "2026-11-25", "channel": "telegram", "item": "x", "status": "published"}]


def test_the_topic_is_the_weeks_talking_point_from_anywhere_and_must_be_fresh():
    p = live.write_prompt("trend", DAY, [])
    assert "any country" in p and "DISAGREE" in p and '"hooks"' in p and "two defensible answers" in p
    assert "LinkedIn itself cannot be searched" in p                                    # no pretending to read LinkedIn's own trends
    assert "last 3 hours" in p and "then 12, then 24" in p and "Never go past 24 hours" in p
    assert "last 24 hours" in p and live.gate(post(as_of="2026-11-23"), URLS, "trend", DAY, SETTINGS) == []      # yesterday's event, for a post written this evening
    assert any("not within 1 days" in x for x in live.gate(post(), URLS, "trend", DAY, SETTINGS))                # 20 Nov: old news
    assert "trend" in lp.PILLARS and lp.LABELS["trend"] and lp.TOUCH["trend"]


def test_a_panel_picks_the_opening_and_only_from_lines_that_are_short_and_proven():
    asked = []
    def ask(messages, system, searches=8):
        asked.append((messages[0]["content"], searches))
        return {"text": json.dumps({"scores": [[3, 3, 3], [8, 7, 9]]}), "urls": set()}
    p = post(hooks=["Gold lost 4 percent in five days. Your hedge policy was written for a different market.",
                    "Gold fell 9 percent this quarter.",                                 # 9 is in no claim: never shown to the panel
                    "x" * 141])
    assert live.best_hook(p, ask).startswith("Gold lost 4 percent") and asked[0][1] == 0 and "9 percent" not in asked[0][0]
    assert live.best_hook(post(), ask) == post()["hook"] and len(asked) == 1             # one line only: no panel
    def broken(messages, system, searches=8):
        raise live.LiveError("529")
    assert live.best_hook(p, broken) == p["hook"]                                        # the writer's own line stays


def test_the_chosen_opening_is_the_one_the_second_check_judges(tmp_path):
    root = _root(tmp_path)
    seen = []
    def ask(messages, system, searches=8):
        seen.append(messages[0]["content"])
        if len(seen) == 1:
            return {"text": json.dumps(post(as_of="2026-11-23", hooks=["Gold lost 4 percent in a week while the dollar rose."])), "urls": URLS}
        if len(seen) == 2:
            return {"text": json.dumps({"scores": [[2, 2, 2], [9, 9, 9]]}), "urls": set()}
        return {"text": json.dumps({"claims": [{"n": 1, "true": True}], "hook_supported": True, **GOOD}), "urls": set()}
    item, why = live.write("trend", DAY, [], SETTINGS, root=root, ask=ask)
    assert item["hook"] == "Gold lost 4 percent in a week while the dollar rose." and item["pillar"] == "trend" and why == ""
    assert "Hook: Gold lost 4 percent in a week while" in seen[2]


def test_the_evening_tries_the_talking_point_first_and_falls_back_to_the_days_category(tmp_path):
    root = _root(tmp_path)
    (root / "content" / "linkedin_personal.json").write_text(json.dumps({"settings": SETTINGS, "items": []}))
    bank = {"settings": {**SETTINGS, "min_hashtags": 3}, "items": []}
    fresh = {"id": "live-x", "pillar": "trend", "hook": "Hook live", "body": " ".join(["word"] * 120), "question": "Why?", "hashtags": ["#A", "#B"],
             "card": {"title": "T", "points": ["one", "two"]}, "facts": "f", "sources": ["https://www.reuters.com/x"]}
    asked, sent = [], []
    def write_live(cat, day, covered, s):
        asked.append(cat)
        return (fresh, "") if cat == "trend" else (None, "no")
    d = lp.Deps(git_publish=lambda paths, msg: None, notify=sent.append, sync_repo=lambda: None, write_live=write_live, review=lambda root: None)
    thu = datetime(2026, 11, 27, 5, 7, tzinfo=timezone.utc)                              # the morning of Fri 27 Nov (tools day)
    assert lp.evening(thu, root=root, deps=d, bank=bank) == 0
    assert asked == ["trend"] and "This week's talking point" in sent[0] and "which side you take" in sent[0]
    assert json.loads((root / lp.NEXT).read_text())["item"]["pillar"] == "trend"


def test_a_screenshot_captioned_stats_is_read_matched_and_only_its_numbers_are_kept(tmp_path):
    root = _root(tmp_path, LOG)
    assert rv.is_stats({"caption": "Stats"}) and rv.is_stats({"caption": " stats 2026-11-23 "}) and not rv.is_stats({"caption": "li 2026-11-23"})
    posts = rv.recent_posts(root)
    assert [p["date"] for p in posts] == ["2026-11-23", "2026-11-25"] and posts[1]["pillar"] == "trend" and posts[0]["pillar"] == "case"
    saved = []
    def fetch(cfg, file_id, out, call):
        out.write_bytes(b"jpg")
    read = lambda path: [{"first_line": "Amazon gets paid by customers before it pays", "impressions": 412, "reactions": 9, "comments": 3, "reposts": None},
                         {"first_line": "Something he wrote by hand last month", "impressions": 50}]
    msg = {"caption": "stats", "photo": [{"file_id": "f", "width": 900}]}
    reply = rv.stats_reply({}, msg, root, change=lambda root, add, rm, why: saved.append(add), fetch=fetch, read=read, today=date(2026, 11, 26))
    kept = json.loads((root / rv.STATS).read_text())["posts"]
    assert kept["2026-11-23"]["impressions"] == 412 and kept["2026-11-23"]["comments"] == 3 and "reposts" not in kept["2026-11-23"]
    assert "412 impressions" in reply and "Not matched: Something he wrote" in reply and "1 of 3" in reply and saved == [[rv.STATS]]
    assert not (root / "out" / "stats-shot.jpg").exists()                                # public repository: the picture is never kept
    lost = rv.stats_reply({}, msg, root, change=lambda *a: None, fetch=fetch, read=lambda p: [{"first_line": "Unknown words here", "impressions": 5}])
    assert "could not tie" in lost and "stats 2026-11-25" in lost
    dated = rv.stats_reply({}, {**msg, "caption": "stats 2026-11-25"}, root, change=lambda *a: None, fetch=fetch,
                           read=lambda p: [{"first_line": "My own words first", "impressions": 900, "comments": 14}])
    assert "900 impressions" in dated and json.loads((root / rv.STATS).read_text())["posts"]["2026-11-25"]["pillar"] == "trend"


def test_the_bot_takes_a_stats_screenshot_once(tmp_path):
    calls, sent = [], []
    def call(token, method, params=None):
        calls.append((method, params))
        if method == "getUpdates" and not (params or {}).get("offset"):
            return {"result": [{"update_id": 7, "message": {"chat": {"id": 1}, "caption": "stats", "photo": [{"file_id": "f", "width": 9}]}}]}
        return {"result": []}
    n = tg.poll({"token": "t", "chat_id": 1}, tmp_path, call=call, send=lambda cfg, text: sent.append(text), change=lambda *a: None,
                stats_fn=lambda cfg, m, root, call, change: "read")
    assert n == 1 and sent == ["read"] and ("getUpdates", {"offset": 8, "timeout": 0}) in calls


def test_lessons_come_only_from_new_numbers_and_reach_the_next_writer(tmp_path):
    root = _root(tmp_path, LOG)
    asked = []
    def ask(prompt):
        asked.append(prompt)
        return json.dumps({"lessons": ["Open on the named company; Amazon 412 against 60."], "best": "Amazon", "worst": "Gold", "subjects": "Named companies.", "report": "Amazon led."})
    assert rv.review(root, ask) is None and rv.lesson_text(root) == ""                   # no numbers yet: nothing is invented
    rows = [({"date": f"2026-11-{d}", "item": "i", "pillar": "case", "hook": f"Hook {d}", "format": ""}, {"impressions": n}) for d, n in ((16, 60), (18, 90))]
    rv.record(root, rows, date(2026, 11, 26))
    assert rv.review(root, ask) is None and asked == []                                  # two posts cannot be compared
    rv.record(root, [({"date": "2026-11-23", "item": "amazon-ccc", "pillar": "case", "hook": "Amazon", "format": ""}, {"impressions": 412})], date(2026, 11, 26))
    out = rv.review(root, ask, today=date(2026, 11, 26))
    assert out["lessons"] and out["posts"] == 3 and '"impressions": 412' in asked[0]
    assert rv.review(root, ask) is None and len(asked) == 1                              # same numbers: not asked, not told again
    assert "Open on the named company" in rv.lesson_text(root) and "Named companies." in live.write_prompt("news", DAY, [], rv.lesson_text(root))
    told, sent = [], []
    d = lp.Deps(git_publish=lambda paths, msg: told.append(paths), notify=sent.append, sync_repo=lambda: None,
                write_live=lambda *a: (None, "no"), review=lambda root: {"report": "Amazon led."})
    lp.evening(datetime(2026, 11, 27, 5, 7, tzinfo=timezone.utc), root=root, deps=d, bank={"settings": SETTINGS, "items": []})
    assert ["logs/linkedin-lessons.json"] in told and "Amazon led." in sent[0]
