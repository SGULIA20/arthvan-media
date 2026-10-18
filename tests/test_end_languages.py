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


def test_a_story_banner_stays_on_screen_for_every_scene_except_the_end_card():
    from playwright.sync_api import sync_playwright
    from engine.story import TEMPLATE
    scenes = [{"layout": "talk", "dur": 3}, {"layout": "present", "dur": 3, "screen": "x.png"}, {"layout": "scene", "dur": 3, "card": "Hello"}, {"layout": "end", "dur": 5}]
    deck = {"scenes": scenes, "title": "t", "end_line": "e", "app_name": "App", "palette": {"bg": "#000", "bg2": "#111", "fg": "#fff", "muted": "#999", "accent": "#fa0", "good": "#0fa"},
            "chars": "mira", "char_base": "file:///nonexistent", "vo_env": [0.0] * 600, "vo_amp": [0.0] * 600, "disclaimer": "", "link_in_bio": "Link in bio",
            "icon": "file:///nonexistent.png", "badge": "file:///nonexistent.png", "shots": "file:///nonexistent", "langs": {"label": "L", "line": "l"}, "clips": {},
            "banner": "<em>Ek baat</em> jo hum kisi se nahi kehte"}
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1080, "height": 1920})
        pg.add_init_script("window.STORY=" + json.dumps(deck) + ";"); pg.goto(TEMPLATE.as_uri())
        seen = []
        for t in (1.0, 4.0, 7.0, 10.0):
            pg.evaluate(f"render({t})"); seen.append(pg.locator(".banner").count())
        deck["banner"] = ""
        pg.add_init_script("window.STORY=" + json.dumps(deck) + ";"); pg.goto(TEMPLATE.as_uri()); pg.evaluate("render(1.0)")
        none = pg.locator(".banner").count()
        b.close()
    assert seen == [1, 1, 1, 0] and none == 0
