import copy

from engine.config import load_apps
from engine.lint import build_captions, lint_item

APPS = load_apps()


def item(**kw):
    base = {
        "id": "t1",
        "template": "ink",
        "caption": "Plain words about the app.",
        "hashtags": ["#One", "#Two"],
        "slides": [
            {"kind": "hook", "text": "A clear headline"},
            {"kind": "steps", "text": "Three things", "items": ["one", "two", "three"]},
            {"kind": "quote", "text": "A closing line"},
        ],
    }
    base.update(kw)
    return base


def test_clean_item_passes_for_both_apps():
    assert lint_item(APPS["waypoint"], item()) == []
    assert lint_item(APPS["scoremybiz"], item()) == []


def test_waypoint_privacy_and_safety_claims_are_blocked():
    for bad in ("Nobody can see you here", "A secure place", "Stay anonymous", "Never traced", "A safe space", "Good for anxiety"):
        problems = lint_item(APPS["waypoint"], item(caption=bad))
        assert problems, bad


def test_waypoint_banned_word_inside_a_slide_is_blocked():
    it = item()
    it["slides"][0]["text"] = "Complete privacy for everyone"
    assert any("privacy" in p for p in lint_item(APPS["waypoint"], it))


def test_global_promises_are_blocked_for_scoremybiz():
    assert lint_item(APPS["scoremybiz"], item(caption="Guaranteed results"))
    assert lint_item(APPS["scoremybiz"], item(caption="The best app"))


def test_stray_numbers_are_blocked_but_fixed_facts_and_count_words_pass():
    assert lint_item(APPS["scoremybiz"], item(caption="Save 50 rupees a day"))
    assert lint_item(APPS["scoremybiz"], item(caption="Enter 8 numbers and see your score in 5 minutes.")) == []
    assert lint_item(APPS["scoremybiz"], item(caption="Three habits. Try 3 things today.")) == []


def test_numbers_are_allowed_on_a_sample_slide_only():
    it = item()
    it["slides"][0] = {"kind": "stat", "value": "Rs 50,000", "text": "profit on paper"}
    assert lint_item(APPS["scoremybiz"], it)
    it["slides"][0]["sample"] = True
    assert lint_item(APPS["scoremybiz"], it) == []


def test_sample_slide_needs_an_app_with_a_money_disclaimer():
    it = item()
    it["slides"][0] = {"kind": "stat", "value": "50", "text": "x", "sample": True}
    assert any("disclaimer" in p for p in lint_item(APPS["waypoint"], it))


def test_captions_carry_link_link_in_bio_and_disclaimer():
    it = item()
    it["slides"][0] = {"kind": "stat", "value": "Rs 50,000", "text": "profit on paper", "sample": True}
    post, reel = build_captions(APPS["scoremybiz"], it)
    for cap in (post, reel):
        assert APPS["scoremybiz"]["play_url"] in cap
        assert "Link in bio" in cap
        assert "Not financial advice" in cap
        assert len(cap) < 2200
    post, reel = build_captions(APPS["waypoint"], item())
    assert APPS["waypoint"]["play_url"] in post and "Link in bio" in reel
    assert "financial advice" not in post


def test_hashtags_are_capped_at_five_with_item_tags_first():
    it = item(hashtags=["#A", "#B", "#C", "#D"])
    post, _ = build_captions(APPS["scoremybiz"], copy.deepcopy(it))
    tags = [w for w in post.split() if w.startswith("#")]
    assert len(tags) == 5 and tags[:4] == ["#A", "#B", "#C", "#D"]


def test_waypoint_identity_moderation_and_emotional_claims_are_blocked():
    for bad in ("Tomorrow you will be someone else", "Posts are checked by an automated filter", "Let it out",
                "Talk to someone who is listening", "Say what you cannot say anywhere else", "Your real name stays hidden",
                "Good for stress", "You are not alone", "A place to vent", "Moderated by us", "We protect you"):
        assert lint_item(APPS["waypoint"], item(caption=bad)), bad


def test_scoremybiz_regulated_and_money_size_claims_are_blocked():
    for bad in ("Get a loan faster", "Improve your CIBIL", "Save tax with us", "Certified by experts",
                "Earn two lakh more", "Ten percent growth", "Costs fell 5%", "A crore in sales"):
        assert lint_item(APPS["scoremybiz"], item(caption=bad)), bad


def sample_item():
    it = item(hashtags=["#A", "#B"])
    it["slides"][0] = {"kind": "stat", "value": "Rs 50,000", "text": "profit on paper", "sample": True}
    return it


def test_linkedin_text_has_a_clickable_link_not_link_in_bio_and_the_disclaimer():
    from engine.lint import build_linkedin_text
    text, tags = build_linkedin_text(APPS["scoremybiz"], sample_item())
    assert APPS["scoremybiz"]["play_url"] in text and "Link in bio" not in text
    assert "Not financial advice" in text and "#" not in text
    assert tags[:2] == ["#A", "#B"] and len(tags) <= 5
    wtext, _ = build_linkedin_text(APPS["waypoint"], item())
    assert APPS["waypoint"]["play_url"] in wtext and "financial advice" not in wtext


def test_alt_texts_cover_every_slide_plus_the_end_card():
    from engine.lint import alt_texts
    it = sample_item()
    alts = alt_texts(APPS["scoremybiz"], it)
    assert len(alts) == len(it["slides"]) + 1
    assert all(a and len(a) <= 300 for a in alts)
    assert "ScoreMyBiz" in alts[-1]
