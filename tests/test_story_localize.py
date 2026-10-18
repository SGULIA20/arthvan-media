import json

from engine import story_localize as sl

BASE = {"id": "mira-ekbaat-hi", "app": "waypoint", "lang": "hi-IN", "character": "mira", "feature": "reactions", "post_on": "2026-10-21",
        "title": "मैं ठीक हूँ", "caption": "आपकी वो एक बात क्या है?", "banner": "हम सबका एक <em>'मैं ठीक हूँ'</em><br>होता है 🤐",
        "scenes": [{"layout": "illus", "image": "s01.png", "vo": "बचपन में हम हर बात माँ को बताते थे।", "sub": "Bachpan mein hum har baat Maa ko batate the."},
                   {"layout": "phone", "screen": "create_typed.png", "vo": "बस एक सच्ची लाइन लिखिए।", "sub": "Bas ek sachchi line likhiye."},
                   {"layout": "end", "pose": "wave", "vo": "वेपॉइंट। एक बार कहिए।", "sub": ""}]}


def fake_ask(prompt, **kw):
    if "hook line" in prompt:
        return "আমাদের সবার একটা <em>'আমি ঠিক আছি'</em><br>থাকে 🤐"
    return json.dumps({"title": "আমি ঠিক আছি", "caption": "আপনার সেই একটা কথা কী?",
                       "scenes": [{"vo": "ছোটবেলায় সব কথা মাকে বলতাম।"}, {"vo": "শুধু একটা সত্যি লাইন লিখুন।"}, {"vo": "ওয়েপয়েন্ট। একবার বলুন।"}]}, ensure_ascii=False)


def test_a_story_is_made_in_another_language_with_the_same_pictures():
    st = sl.localize_story(BASE, "bn", ask=fake_ask, order=1)
    assert st["id"] == "mira-ekbaat-bn" and st["lang"] == "bn" and st["art_id"] == "mira-ekbaat-hi"      # the pictures of the original are reused
    assert st["scenes"][0]["vo"] == st["scenes"][0]["sub"] == "ছোটবেলায় সব কথা মাকে বলতাম।"                  # subtitle = the spoken line, in the language's own script
    assert st["scenes"][1]["screen"] == "create_typed.png" and st["scenes"][2]["sub"] == ""                  # screens and the end card are untouched
    assert st["banner"].count("<em>") == 1 and st["banner"].count("<br>") == 1 and st["machine_translated"] is True
    assert st["post_on"] == "2026-10-25" and st["feature"] != "reactions"                                      # a few days later, labelled with another live feature


def test_a_banner_that_loses_its_tags_is_refused():
    import pytest
    from engine import translator
    with pytest.raises(translator.TranslationRejected):
        sl.translate_banner("A <em>b</em><br>c", "bn", ask=lambda *a, **k: "just text")


def test_the_original_story_is_not_changed():
    before = json.dumps(BASE, sort_keys=True)
    sl.localize_story(BASE, "bn", ask=fake_ask)
    assert json.dumps(BASE, sort_keys=True) == before
