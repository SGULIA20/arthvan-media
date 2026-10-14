import pytest

from engine.localize import localize, localized_id

BASE = {"id": "lumi-daily-en", "app": "scoremybiz", "lang": "en", "character": "lumi", "voice": "Lekha", "legacy": True, "post_on": "2026-11-07",
        "title": "T", "caption": "C", "cast": {"a": "x"},
        "scenes": [{"layout": "clip", "clip": "shot", "vo": "Hello", "sub": "Hello", "refs": ["lumi"], "screen": "book.png", "min": 8, "card": "Card"},
                   {"layout": "end", "pose": "front_happy", "vo": "End", "sub": "", "min": 5}]}
TR = {"title": "शीर्षक", "caption": "कैप्शन", "scenes": [{"vo": "नमस्ते", "card": "कार्ड"}, {"vo": "अंत"}]}


def test_a_translation_changes_words_and_voice_but_keeps_the_filmed_shots_screens_and_timing():
    st = localize(BASE, TR, "hi")
    assert st["id"] == "lumi-daily-hi" and st["lang"] == "hi-IN" and st["title"] == "शीर्षक" and st["caption"] == "कैप्शन"
    s0, s1 = st["scenes"]
    assert s0["vo"] == "नमस्ते" and s0["sub"] == "नमस्ते" and s0["card"] == "कार्ड"           # subtitles follow the voice unless given separately
    assert s0["clip"] == "shot" and s0["refs"] == ["lumi"] and s0["screen"] == "book.png" and s0["min"] == 8 and st["cast"] == {"a": "x"}
    assert s1["vo"] == "अंत" and s1["sub"] == "" and s1["pose"] == "front_happy"
    assert "legacy" not in st and "voice" not in st and BASE["lang"] == "en" and BASE["scenes"][0]["vo"] == "Hello"   # the original is untouched


def test_a_translation_with_the_wrong_number_of_scenes_is_refused():
    with pytest.raises(ValueError, match="2 scenes"):
        localize(BASE, {"scenes": [{"vo": "x"}]}, "hi")


def test_ids_swap_the_language_suffix():
    assert localized_id("founder-card-en", "es") == "founder-card-es" and localized_id("lumi-navratri-gu", "hi") == "lumi-navratri-gu-hi"
