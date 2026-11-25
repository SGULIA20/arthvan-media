import json
from datetime import date
from pathlib import Path

import pytest

from engine import linkedin_personal as lp

DAY = date(2026, 10, 19)                 # a Monday: LinkedIn posts Mon/Wed/Fri (founder, 29 Oct 2026)


@pytest.fixture(autouse=True)
def _api_posting(monkeypatch, request):
    """The tests below cover the engine posting through the API; since 24 Nov 2026 the founder posts himself (SELF_POST), tested at the end."""
    if "self_post" not in request.node.name:
        monkeypatch.setattr(lp, "SELF_POST", False)


def item(**over):
    base = {"id": "toc", "pillar": "model", "hook": "You are not as fast as your slowest process.",
            "body": "Every system has one bottleneck.\n\nFix that one first.", "question": "Where is yours?",
            "hashtags": ["#TheoryOfConstraints", "#OperationalExcellence"],
            "card": {"kicker": "Model", "title": "Theory of Constraints", "points": ["Identify", "Exploit", "Subordinate"]}}
    base.update(over)
    return base


def settings():
    return {"base_hashtags": ["#SGLearning"], "max_hashtags": 5, "min_hashtags": 3, "already_posted": ["Broken Window"]}


# ---------- bank + lint ----------
def test_every_bank_item_passes_lint_and_validates():
    bank = lp.load_personal()
    assert len(bank["items"]) >= 45
    for it in bank["items"]:
        assert lp.lint_personal(it, bank["settings"]) == [], it["id"]


def test_bank_ids_unique_and_pillars_rotate():
    items = lp.load_personal()["items"]
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    assert {i["pillar"] for i in items} <= set(lp.PILLARS)
    unused = {i["pillar"] for i in items} & set(lp.CYCLE)
    assert unused >= set(lp.CYCLE) - set(lp.LIVE)                    # every bank category of the brief has posts waiting (21 Nov 2026)


def test_lint_refuses_digits_without_facts():
    assert any("number" in p for p in lp.lint_personal(item(body="Kodak built it in 1975."), settings()))
    assert lp.lint_personal(item(body="Kodak built it in 1975.", facts="Kodak engineer Steven Sasson, 1975"), settings()) == []


def test_lint_refuses_em_dash_six_hashtags_long_hook_and_missing_question_mark():
    assert any("em-dash" in p for p in lp.lint_personal(item(body="Think — then act."), settings()))
    assert any("hashtags" in p for p in lp.lint_personal(item(hashtags=["#a", "#b", "#c", "#d", "#e"]), settings()))   # + #SGLearning = 6
    assert any("hashtags" in p for p in lp.lint_personal(item(hashtags=["#a"]), settings()))                            # only 2
    assert any("hook" in p for p in lp.lint_personal(item(hook="x" * 201), settings()))
    assert any("question" in p for p in lp.lint_personal(item(question="Think about it."), settings()))
    assert any("banned" in p for p in lp.lint_personal(item(body="This is the best model ever."), settings()))


def test_lint_refuses_seven_slides_and_bad_cards():
    c = item()["card"]
    assert any("slides" in p for p in lp.lint_personal(item(slides=[c] * 7), settings()))
    assert any("slides" in p for p in lp.lint_personal(item(slides=[c]), settings()))
    assert any("title" in p for p in lp.lint_personal(item(card=dict(c, title="t" * 61)), settings()))
    assert any("points" in p for p in lp.lint_personal(item(card=dict(c, points=["p"] * 6)), settings()))


# ---------- selection + text ----------
def write_log(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_pick_takes_first_unused_in_bank_order(tmp_path):
    log = tmp_path / "logs" / "posts.jsonl"
    items = [item(id="a"), item(id="b", pillar="finance"), item(id="c", pillar="ai")]
    write_log(log, [{"date": "2026-10-19", "channel": "linkedin_personal", "item": "a", "status": "published"},
                    {"date": "2026-10-19", "channel": "linkedin", "item": "b", "status": "published"}])     # other channel does not count
    assert lp.pick(DAY, items, log)["id"] == "b"


def test_pick_wraps_to_least_recent_when_all_used(tmp_path):
    log = tmp_path / "logs" / "posts.jsonl"
    items = [item(id="a"), item(id="b", pillar="finance")]
    write_log(log, [{"date": "2026-10-01", "channel": "linkedin_personal", "item": "b", "status": "published"},
                    {"date": "2026-10-02", "channel": "linkedin_personal", "item": "a", "status": "published"},
                    {"date": "2026-10-03", "channel": "linkedin_personal", "item": "b", "status": "failed"}])   # a failure is not a use
    assert lp.pick(DAY, items, log)["id"] == "b"


def test_build_text_is_hook_body_question_and_tags_with_sglearning_last():
    text, tags = lp.build_text(item(), settings())
    assert text == "You are not as fast as your slowest process.\n\nEvery system has one bottleneck.\n\nFix that one first.\n\nWhere is yours?"
    assert tags == ["#TheoryOfConstraints", "#OperationalExcellence", "#SGLearning"]
    assert lp.alt_text(item()["card"]) == "Theory of Constraints: Identify, Exploit, Subordinate"


# ---------- run ----------
class Deps:
    def __init__(self, fail=False):
        self.posted, self.published, self.sent, self.rendered, self.fail = [], [], [], [], fail

    def render_cards(self, it, out_dir):
        self.rendered.append(it["id"]); return [Path(out_dir) / "card_1.jpg"]

    def post_images(self, token, urn, text, tags, paths, alts):
        if self.fail:
            raise lp.LinkedInError("HTTP 500")
        self.posted.append((text, tags, paths, alts)); return "urn:li:share:99"

    def make_pdf(self, pages, out):
        return Path(out)

    def post_document(self, token, urn, text, tags, pdf, title):
        if self.fail or getattr(self, "doc_fail", False):
            raise lp.LinkedInError("HTTP 422")
        self.posted.append((text, tags, [pdf], title)); return "urn:li:share:77"

    def git_publish(self, paths, message):
        self.published.append(message)

    def notify(self, text):
        self.sent.append(text)

    def sync_repo(self):
        pass


ENV = {"LINKEDIN_ACCESS_TOKEN": "T", "LINKEDIN_PERSON_URN": "urn:li:person:x"}


def bank():
    return {"settings": settings(), "items": [item(id="a"), item(id="b", pillar="finance")]}


def test_post_logs_published_and_notifies(tmp_path):
    d = Deps()
    assert lp.run("post", DAY, root=tmp_path, env=ENV, deps=d, bank=bank()) == 0
    rows = [json.loads(l) for l in (tmp_path / "logs" / "posts.jsonl").read_text().splitlines()]
    assert rows[-1] == {"date": "2026-10-19", "channel": "linkedin_personal", "item": "a", "status": "published", "id": "urn:li:share:99",
                        "format": "picture"}
    assert d.posted[0][1] == ["#TheoryOfConstraints", "#OperationalExcellence", "#SGLearning"]
    assert d.published and "linkedin.com/feed/update/urn:li:share:99" in d.sent[0]


def test_second_run_same_day_is_a_noop_and_next_day_takes_the_next_item(tmp_path):
    d = Deps()
    lp.run("post", DAY, root=tmp_path, env=ENV, deps=d, bank=bank())
    assert lp.run("post", DAY, root=tmp_path, env=ENV, deps=d, bank=bank()) == 0 and len(d.posted) == 1
    lp.run("post", date(2026, 10, 23), root=tmp_path, env=ENV, deps=d, bank=bank())
    assert d.rendered == ["a", "b"]                            # Monday and Friday: the picture only


def test_pause_stops_posting_and_prepare_never_posts(tmp_path):
    d = Deps()
    assert lp.run("post", DAY, root=tmp_path, env=dict(ENV, PAUSE="1"), deps=d, bank=bank()) == 0 and not d.rendered
    assert lp.run("prepare", DAY, root=tmp_path, env=ENV, deps=d, bank=bank()) == 0
    assert d.rendered == ["a"] and not d.posted and not (tmp_path / "logs" / "posts.jsonl").exists()


def test_failed_post_logs_failed_and_returns_1(tmp_path):
    d = Deps(fail=True)
    assert lp.run("post", DAY, root=tmp_path, env=ENV, deps=d, bank=bank()) == 1
    rows = [json.loads(l) for l in (tmp_path / "logs" / "posts.jsonl").read_text().splitlines()]
    assert rows[-1]["status"] == "failed" and "HTTP 500" in rows[-1]["error"]
    assert lp.run("post", DAY, root=tmp_path, env=ENV, deps=Deps(), bank=bank()) == 0      # a later retry the same day may post


def test_missing_credentials_is_an_error_in_post_mode_only(tmp_path):
    assert lp.run("post", DAY, root=tmp_path, env={}, deps=Deps(), bank=bank()) == 1
    assert lp.run("render", DAY, root=tmp_path, env={}, deps=Deps(), bank=bank()) == 0


@pytest.mark.slow
def test_render_cards_makes_one_jpeg_per_card(tmp_path):
    from engine.render import verify_image
    paths = lp.render_cards(item(slides=[item()["card"], dict(item()["card"], title="Second card", points=[])]), tmp_path)
    assert [p.name for p in paths] == ["card_1.jpg", "card_2.jpg"]
    for p in paths:
        assert verify_image(p, 1080, 1350) == []


def test_a_bad_picture_or_an_odd_api_body_is_logged_failed_and_reported(tmp_path):
    class Bad(Deps):
        def render_cards(self, it, out_dir):
            raise RuntimeError("card_1.jpg: looks blank")
    d = Bad()
    assert lp.run("post", DAY, root=tmp_path, env=ENV, deps=d, bank=bank()) == 1
    rows = [json.loads(l) for l in (tmp_path / "logs" / "posts.jsonl").read_text().splitlines()]
    assert rows[-1]["status"] == "failed" and "looks blank" in rows[-1]["error"] and "picture" in d.sent[0]

    class Odd(Deps):
        def post_images(self, *a):
            raise KeyError("value")
    d = Odd()
    assert lp.run("post", DAY, root=tmp_path, env=ENV, deps=d, bank=bank()) == 1
    assert "post" in d.sent[0] and d.published
    assert lp.run("prepare", DAY, root=tmp_path, env=ENV, deps=Bad(), bank=bank()) == 1      # prepare reports, never logs


def test_log_push_is_retried_and_a_lost_push_warns_loudly(tmp_path):
    class Flaky(Deps):
        def __init__(self, fails):
            super().__init__(); self.fails, self.slept = fails, []

        def git_publish(self, paths, message):
            if self.fails:
                self.fails -= 1; raise RuntimeError("push rejected")
            self.published.append(message)

        def sleep(self, s):
            self.slept.append(s)
    d = Flaky(2)
    assert lp.run("post", DAY, root=tmp_path, env=ENV, deps=d, bank=bank()) == 0 and d.published and d.slept == [20, 20]
    d = Flaky(9)
    assert lp.run("post", date(2026, 10, 23), root=tmp_path, env=ENV, deps=d, bank=bank()) == 1
    assert "/pause" in d.sent[-1] and "linkedin.com/feed/update/" in d.sent[-1]


def test_lint_survives_a_null_question():
    assert any("question" in p for p in lp.lint_personal(item(question=None), settings()))


def test_lint_refuses_topics_the_founder_already_posted_himself():
    assert any("already posted" in p for p in lp.lint_personal(item(body="The Broken Window theory says fix it early."), settings()))
    posted = lp.load_personal()["settings"]["already_posted"]
    for t in ("Theory of Constraints", "FISHMaN", "TOWS", "first mover", "two continents", "OPPIC"):
        assert t in posted


def test_lane_banned_list_replaces_the_global_one_and_every_number_has_a_source():
    s = dict(settings(), banned_phrases=["guarantee"])
    assert lp.lint_personal(item(body="Profit fell 11 percent.", facts="HBR 1992"), s) == []       # percent is fine here with a source
    assert any("banned" in p for p in lp.lint_personal(item(body="We guarantee it."), s))
    bank = lp.load_personal()
    for it in bank["items"]:
        if any(ch.isdigit() for ch in it["body"] + it["hook"]):
            assert it.get("facts"), it["id"]
        if it["card"].get("stat"):
            assert it["card"].get("source"), it["id"]


def test_wednesday_posts_a_picture_now_not_a_document(tmp_path):
    """21 Nov 2026: his export gave pictures 127 impressions a post and documents 64, so the Wednesday document stopped."""
    d = Deps()
    assert lp.run("post", date(2026, 10, 28), root=tmp_path, env=ENV, deps=d, bank=bank()) == 0          # a Wednesday
    row = json.loads((tmp_path / "logs" / "posts.jsonl").read_text().splitlines()[-1])
    assert row["format"] == "picture" and row["id"] == "urn:li:share:99"


def test_deck_is_hook_card_points_question():
    it = item(id="a")
    pages = lp.deck(it)
    assert pages[0]["title"] == it["hook"] and pages[1] == it["card"] and pages[-1]["kicker"] == "Your turn"
    assert len(pages) == 3 + len(it["card"].get("points", []))


def test_tuesday_thursday_and_weekends_post_nothing(tmp_path):
    for day in (date(2026, 10, 27), date(2026, 10, 29), date(2026, 10, 31), date(2026, 11, 1)):
        d = Deps()
        assert lp.run("post", day, root=tmp_path, env=ENV, deps=d, bank=bank()) == 0
    assert not (tmp_path / "logs" / "posts.jsonl").exists()


# ---------- the founder's brief (21 Nov 2026): seven categories, his own picture, the evening request ----------
def _brief_item(i, pillar, words=120):
    return {"id": i, "pillar": pillar, "hook": f"Hook {i}", "body": " ".join(["word"] * words), "question": "Why?",
            "hashtags": ["#A", "#B"], "card": {"title": f"Title {i}", "points": ["one", "two"]}, "facts": "test"}


def test_categories_rotate_over_the_three_weekly_slots_and_live_ones_never_come_from_the_bank(tmp_path):
    from datetime import date
    days = [date(2026, 11, 23), date(2026, 11, 25), date(2026, 11, 27), date(2026, 11, 30), date(2026, 12, 2), date(2026, 12, 4), date(2026, 12, 7)]
    assert [lp.category_for(d) for d in days] == list(lp.CYCLE) and lp.category_for(date(2026, 12, 9)) == "case"
    assert lp.category_for(date(2026, 11, 20)) is None
    settings = {"base_hashtags": ["#SG"], "min_hashtags": 3, "max_hashtags": 5, "banned_phrases": ["guarantee"]}
    items = [_brief_item("t1", "tools"), _brief_item("m1", "markets"), _brief_item("c1", "case")]
    log = tmp_path / "posts.jsonl"; log.write_text("")
    assert lp.choose(date(2026, 11, 23), items, log, settings, tmp_path)["id"] == "c1"          # Monday: a case study
    assert lp.choose(date(2026, 11, 25), items, log, settings, tmp_path)["id"] == "t1"          # markets day, nothing written: the bank, never m1
    assert "body is 60 words" in " ".join(lp.lint_personal(_brief_item("s", "case", 60), settings))   # his word limit holds


def test_the_evening_run_plans_the_post_asks_for_the_picture_once_and_the_morning_uses_it(tmp_path):
    from datetime import date, datetime, timezone
    from PIL import Image
    (tmp_path / "content").mkdir(); (tmp_path / "logs").mkdir(); (tmp_path / "logs" / "posts.jsonl").write_text("")
    settings = {"base_hashtags": ["#SG"], "min_hashtags": 3, "max_hashtags": 5, "banned_phrases": ["guarantee"]}
    bank = {"settings": settings, "items": [_brief_item("t1", "tools"), {**_brief_item("c1", "case"), "scene": "a warehouse at dawn"}]}
    (tmp_path / "content" / "linkedin_personal.json").write_text(json.dumps(bank))
    sent, pushed, posted = [], [], []
    deps = lp.Deps(render_cards=lambda item, out: ["card.jpg"], post_images=lambda tok, urn, text, tags, paths, alts: posted.append(paths) or "urn:li:share:1",
                   git_publish=lambda paths, msg: pushed.append(msg), notify=sent.append, sync_repo=lambda: None, sleep=lambda s: None)
    sat = datetime(2026, 11, 21, 17, 7, tzinfo=timezone.utc)                                    # Saturday evening: Monday is two days off
    assert lp.evening(sat, root=tmp_path, deps=deps, bank=bank) == 0 and sent == []
    sun = datetime(2026, 11, 23, 5, 7, tzinfo=timezone.utc)                                     # Monday 06:07 Lagos: the morning of the post
    assert lp.evening(datetime(2026, 11, 22, 17, 7, tzinfo=timezone.utc), root=tmp_path, deps=deps, bank=bank) == 0 and sent == []   # the evening before: nothing now
    assert lp.next_post_day(sun) == date(2026, 11, 23)
    assert lp.evening(sun, root=tmp_path, deps=deps, bank=bank) == 0
    assert len(sent) == 2 and "Hook c1" in sent[0] and "a warehouse at dawn" in sent[1] and "li 2026-11-23" in sent[1] and "No text" in sent[1]
    assert json.loads((tmp_path / lp.NEXT).read_text())["item_id"] == "c1"
    assert lp.evening(sun, root=tmp_path, deps=deps, bank=bank) == 0 and len(sent) == 2          # a second slot the same evening: silent
    late = datetime(2026, 11, 23, 0, 30, tzinfo=timezone.utc)                                   # GitHub fires late, 01:30 Lagos: still Monday's post
    assert lp.next_post_day(late) == date(2026, 11, 23)
    env = {"LINKEDIN_ACCESS_TOKEN": "t", "LINKEDIN_PERSON_URN": "u"}
    pic = tmp_path / lp.PICTURE_DIR / "2026-11-23.jpg"; pic.parent.mkdir(parents=True)
    Image.effect_noise((1200, 1500), 60).convert("RGB").save(pic, quality=95)
    assert lp.run("post", date(2026, 11, 23), root=tmp_path, env=env, deps=deps, bank=bank) == 0
    assert posted == [[pic]]                                                                    # his picture, not the drawn card
    entry = [json.loads(l) for l in (tmp_path / "logs" / "posts.jsonl").read_text().splitlines()][-1]
    assert entry["item"] == "c1" and entry["format"] == "founder-picture"
    pic.unlink()
    assert lp.run("post", date(2026, 11, 25), root=tmp_path, env=env, deps=deps, bank=bank) == 0 and posted[-1] == ["card.jpg"]   # no picture: the card


def test_a_live_category_uses_the_fresh_post_past_the_gate_and_the_bank_when_it_fails(tmp_path):
    from datetime import datetime, timezone
    (tmp_path / "content").mkdir(); (tmp_path / "logs").mkdir(); (tmp_path / "logs" / "posts.jsonl").write_text("")
    settings = {"base_hashtags": ["#SG"], "min_hashtags": 3, "max_hashtags": 5, "banned_phrases": ["guarantee"]}
    bank = {"settings": settings, "items": [_brief_item("t1", "tools")]}
    (tmp_path / "content" / "linkedin_personal.json").write_text(json.dumps(bank))
    tue = datetime(2026, 11, 25, 5, 7, tzinfo=timezone.utc)                                     # the morning of Wed 25 Nov: markets
    fresh = {**_brief_item("live-gold", "markets"), "sources": ["https://www.reuters.com/x"], "scene": "gold bars"}
    def deps_with(result):
        sent = []
        return sent, lp.Deps(render_cards=lambda item, out: ["card.jpg"], post_images=lambda *a: "urn:li:share:1", git_publish=lambda paths, msg: None,
                             notify=sent.append, sync_repo=lambda: None, sleep=lambda s: None, write_live=lambda cat, day, covered, s: result)
    sent, d = deps_with((fresh, ""))
    assert lp.evening(tue, root=tmp_path, deps=d, bank=bank) == 0
    assert "Hook live-gold" in sent[0] and "Sources checked" in sent[0] and "gold bars" in sent[1]
    assert json.loads((tmp_path / lp.NEXT).read_text())["item"]["id"] == "live-gold"            # the whole post is saved for the morning
    assert lp.planned(tmp_path, date(2026, 11, 25))["id"] == "live-gold"
    (tmp_path / lp.NEXT).unlink()
    sent, d = deps_with((None, "fewer than two sites back: gold fell"))
    assert lp.evening(tue, root=tmp_path, deps=d, bank=bank) == 0
    assert "Hook t1" in sent[0] and "fact check did not pass" in sent[0] and "fewer than two sites" in sent[0]



def test_self_post_hands_the_draft_and_the_picture_to_the_founder_and_posts_nothing(tmp_path):
    """Founder, 24 Nov 2026: 'draft the posts with pics and let me post them ... personal touch'."""
    from datetime import date, datetime, timezone
    (tmp_path / "content").mkdir(); (tmp_path / "logs").mkdir(); (tmp_path / "logs" / "posts.jsonl").write_text("")
    settings = {"base_hashtags": ["#SG"], "min_hashtags": 3, "max_hashtags": 5, "banned_phrases": ["guarantee"]}
    bank = {"settings": settings, "items": [_brief_item("t1", "tools"), _brief_item("c1", "case")]}
    (tmp_path / "content" / "linkedin_personal.json").write_text(json.dumps(bank))
    sent, photos, posted = [], [], []
    deps = lp.Deps(render_cards=lambda item, out: ["card.jpg"], post_images=lambda *a: posted.append(a) or "urn:li:share:1", send_photo=lambda path, cap="": photos.append(path) or True,
                   git_publish=lambda paths, msg: None, notify=sent.append, sync_repo=lambda: None, sleep=lambda s: None)
    assert lp.evening(datetime(2026, 11, 23, 5, 7, tzinfo=timezone.utc), root=tmp_path, deps=deps, bank=bank) == 0
    assert "DRAFT" in sent[0] and "YOUR TOUCH" in sent[0] and "company you worked in" in sent[0] and "li 2026-11-23" in sent[1]
    assert lp.run("post", date(2026, 11, 23), root=tmp_path, env={}, deps=deps, bank=bank) == 0      # no LinkedIn token needed
    assert posted == [] and photos == ["card.jpg"] and "YOUR TOUCH" in sent[-1] and len(sent) == 3            # two evening messages, one in the morning
    assert "https://www.linkedin.com/feed/?shareActive=true&text=Hook%20c1" in sent[-1]                          # one tap opens the post box, written
    assert sent[-1].count("Body") == 0                                                                           # the text itself is not sent a second time
    entry = [json.loads(l) for l in (tmp_path / "logs" / "posts.jsonl").read_text().splitlines()][-1]
    assert entry["status"] == "handed" and entry["item"] == "c1"
    n = len(sent)
    assert lp.run("post", date(2026, 11, 23), root=tmp_path, env={}, deps=deps, bank=bank) == 0 and len(sent) == n   # the safety run an hour later: silent
    assert "c1" in lp.used_ids(tmp_path / "logs" / "posts.jsonl")                                   # a handed draft is not drafted again
