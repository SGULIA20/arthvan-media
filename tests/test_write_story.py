import json
import pytest
from engine import write_story as w, claims


def fake(screens, bad_screen=False):
    scenes = [{"kind": "illus", "vo": f"वाक्य {i}", "sub": f"Vakya {i}", "art": f"Scene {i}"} for i in range(9)]
    scenes.insert(3, {"kind": "phone", "vo": "ऐप", "sub": "App", "screen": "nope.png" if bad_screen else screens[0]})
    return json.dumps({"title": "T", "banner": "B<br><em>x</em>", "caption": "C 👇", "linkedin_text": "L", "cast": {"Anaya": "a girl"}, "scenes": scenes})


def _setup():
    feats, smap = claims.load()
    feature = w.pick_feature("scoremybiz", feats, smap)
    screens = w.feature_screens("scoremybiz", feature, smap)
    tmpl = w.art_template("scoremybiz")
    return feats, smap, feature, screens, tmpl


def test_pick_skips_covered_and_builds_a_valid_story():
    feats, smap, feature, screens, tmpl = _setup()
    assert feature not in w.covered_features("scoremybiz")
    st = w.build("scoremybiz", feature, w.parse("noise " + fake(screens)), tmpl, feats, smap)
    assert st["id"] == f"lumi-{feature}-hi" and st["scenes"][-1]["layout"] == "end"
    assert claims.story_problems(st, feats, smap) == []


def test_a_screen_of_another_feature_is_rejected():
    feats, smap, feature, screens, tmpl = _setup()
    with pytest.raises(w.WriterError):
        w.build("scoremybiz", feature, w.parse(fake(screens, bad_screen=True)), tmpl, feats, smap)
