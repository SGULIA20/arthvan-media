import json
from datetime import date
from pathlib import Path

import pytest

from engine import linkedin_personal as lp

DAY = date(2026, 10, 20)


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
    for a, b in zip(items, items[1:]):
        assert a["pillar"] != b["pillar"], (a["id"], b["id"])
    assert {i["pillar"] for i in items} == set(lp.PILLARS)


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
    assert rows[-1] == {"date": "2026-10-20", "channel": "linkedin_personal", "item": "a", "status": "published", "id": "urn:li:share:99",
                        "format": "picture"}
    assert d.posted[0][1] == ["#TheoryOfConstraints", "#OperationalExcellence", "#SGLearning"]
    assert d.published and "linkedin.com/feed/update/urn:li:share:99" in d.sent[0]


def test_second_run_same_day_is_a_noop_and_next_day_takes_the_next_item(tmp_path):
    d = Deps()
    lp.run("post", DAY, root=tmp_path, env=ENV, deps=d, bank=bank())
    assert lp.run("post", DAY, root=tmp_path, env=ENV, deps=d, bank=bank()) == 0 and len(d.posted) == 1
    lp.run("post", date(2026, 10, 21), root=tmp_path, env=ENV, deps=d, bank=bank())
    assert d.rendered == ["a", "b", "b"]                       # Wednesday: the picture (the fallback) and the document pages


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
    assert lp.run("post", date(2026, 10, 21), root=tmp_path, env=ENV, deps=d, bank=bank()) == 1
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


def test_monday_wednesday_friday_post_a_document_and_fall_back_to_the_picture(tmp_path):
    d = Deps()
    assert lp.run("post", date(2026, 10, 26), root=tmp_path, env=ENV, deps=d, bank=bank()) == 0          # a Monday
    row = json.loads((tmp_path / "logs" / "posts.jsonl").read_text().splitlines()[-1])
    assert row["format"] == "document" and row["id"] == "urn:li:share:77" and "Reply to every comment" in d.sent[-1]
    d2 = Deps(); d2.doc_fail = True
    assert lp.run("post", date(2026, 10, 26), root=tmp_path / "x", env=ENV, deps=d2, bank=bank()) == 0
    row = json.loads((tmp_path / "x" / "logs" / "posts.jsonl").read_text().splitlines()[-1])
    assert row["format"] == "picture" and row["id"] == "urn:li:share:99"


def test_deck_is_hook_card_points_question():
    it = item(id="a")
    pages = lp.deck(it)
    assert pages[0]["title"] == it["hook"] and pages[1] == it["card"] and pages[-1]["kicker"] == "Your turn"
    assert len(pages) == 3 + len(it["card"].get("points", []))
