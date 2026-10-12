from collections import Counter

from radar.report import THEMES, score, texts


def test_every_theme_regex_compiles_and_scores_known_text():
    row = {"play": {"title": "Khata Book", "short": "Udhar khata, GST bills and payment reminders on WhatsApp", "about": "Free for shops. Diwali offer."},
           "youtube": [{"id": "x", "title": "Collect your dues before Diwali"}]}
    sc = score("scoremybiz", row)
    assert sc["collect dues / udhar"] >= 3 and sc["GST and bills"] >= 2 and sc["festival season"] >= 2 and sc["WhatsApp and sharing"] >= 1
    assert isinstance(sc, Counter) and set(sc) == set(THEMES["scoremybiz"])


def test_waypoint_themes_score_their_vocabulary():
    row = {"play": {"title": "Tellonym", "short": "Anonymous questions from friends", "about": "Ask me anything. Chat and meet people."}, "youtube": []}
    sc = score("waypoint", row)
    assert sc["anonymous / no identity"] >= 1 and sc["questions and prompts"] >= 2 and sc["meet people / chat"] >= 2


def test_texts_survives_missing_fields():
    assert texts({"play_error": "HTTPError"}) == ""
