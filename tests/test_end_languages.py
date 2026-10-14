import json
import pytest

from engine.config import ROOT
from engine.story import end_languages


def test_every_app_names_its_languages_and_the_counts_match_the_apps():
    apps = json.loads((ROOT / "content" / "apps.json").read_text())
    sm, wp = end_languages(apps["scoremybiz"]), end_languages(apps["waypoint"])
    assert sm["label"] == "Works in 25 Indian and international languages" and wp["label"] == "Speaks 16 Indian and international languages"   # 25 locale files in ScoreMyBizMobile/lib/locales; 16 in Waypoint (14 packs + English + Hindi)
    assert "हिन्दी" in sm["line"] and sm["line"].count("nowrap") == 25 and "Yorùbá" in sm["line"] and "Kiswahili" in wp["line"]
    assert len(set(apps["scoremybiz"]["languages"])) == 25 and len(set(apps["waypoint"]["languages"])) == 16


def test_a_reel_cannot_be_rendered_for_an_app_without_languages():
    with pytest.raises(ValueError, match="languages"):
        end_languages({"name": "NewApp"})


def test_the_end_card_template_always_prints_the_languages():
    html = (ROOT / "engine" / "templates" / "story2.html").read_text()
    end = html[html.index("function endHTML("):html.index("window.render=")]
    assert "D.langs" in end and "L.label" in end and "L.line" in end


def test_a_language_can_override_the_end_card_texts():
    from engine.config import ROOT
    apps = json.loads((ROOT / "content" / "apps.json").read_text())
    hi = {**apps["scoremybiz"], **apps["scoremybiz"]["i18n"]["hi"]}
    assert end_languages(hi)["label"] == "25 भारतीय और अंतरराष्ट्रीय भाषाओं में उपलब्ध" and hi["link_in_bio"] == "लिंक बायो में"
    assert apps["scoremybiz"]["end_line"] == "Free for 30 days. No credit card."            # English is untouched
