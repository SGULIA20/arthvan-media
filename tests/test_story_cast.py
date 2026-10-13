import pytest
from engine.story import cast_prompt


def test_cast_names_are_filled_in_and_unknown_names_fail_loudly():
    cast = {"suresh": "a middle-aged Indian man in glasses and a checked shirt"}
    assert cast_prompt("{suresh} opens the drawer; {suresh} sighs.", cast) == "a middle-aged Indian man in glasses and a checked shirt opens the drawer; a middle-aged Indian man in glasses and a checked shirt sighs."
    assert cast_prompt("a lane of shops at night", cast) == "a lane of shops at night"
    with pytest.raises(KeyError):
        cast_prompt("{meena} at the counter", cast)


def test_price_line_counts_only_uncached_shots(tmp_path, monkeypatch):
    from engine import broll, story
    monkeypatch.setattr(broll, "BROLL_DIR", tmp_path)
    monkeypatch.setattr(broll, "LEDGER", tmp_path / "l.json")
    monkeypatch.setattr(broll, "status_line", lambda *a, **k: "status")
    st = {"id": "x", "cast": {"a": "Asha"}, "scenes": [{"clip": "{a} at a counter"}, {"clip": "a street"}, {"vo": "no shot"}]}
    (tmp_path / (broll.key_for("Asha at a counter", 8) + ".mp4")).write_bytes(b"x")
    line = story.price_line(st)
    assert "2 filmed shots, 1 already made, 1 new" in line and f"₹{round(8 * broll.INR_PER_SECOND)}" in line


def test_every_new_reel_is_filed_in_the_one_folder_and_nothing_is_replaced(tmp_path):
    from engine.story import file_in_reels_folder
    folder = tmp_path / "Arthvan-Reels"; folder.mkdir()
    (folder / "01-first-en.mp4").write_bytes(b"one"); (folder / "02-second-hi.mp4").write_bytes(b"two")
    mp4 = tmp_path / "new.mp4"; mp4.write_bytes(b"three")
    a = file_in_reels_folder(mp4, "third-en", folder)
    assert a.name == "03-third-en.mp4" and a.read_bytes() == b"three"
    mp4.write_bytes(b"changed")
    assert file_in_reels_folder(mp4, "first-en", folder).read_bytes() == b"one"           # an existing Reel is never replaced
    assert file_in_reels_folder(mp4, "third-en", folder).read_bytes() == b"three"
    assert sorted(f.name for f in folder.glob("*.mp4")) == ["01-first-en.mp4", "02-second-hi.mp4", "03-third-en.mp4"]


def test_a_filmed_story_converts_to_the_in_house_cutout_style_without_any_shot():
    from engine.story import cutout_story, shot_plan
    st = {"id": "x", "character": "lumi", "cast": {"a": "Asha"}, "scenes": [
        {"layout": "clip", "clip": "{a} talks", "refs": ["lumi"], "vo": "Hi", "sub": "Hi", "title": "T", "min": 8},
        {"layout": "clip", "clip": "{a} counts", "vo": "One", "sub": "One", "card": "Night", "min": 8},
        {"layout": "clip", "clip": "{a} taps", "screen": "book.png", "vo": "Two", "sub": "Two", "min": 8},
        {"layout": "end", "pose": "front_happy", "vo": "End", "sub": "", "min": 5}]}
    c = cutout_story(st)
    assert shot_plan(c) == [] and c["style"] == "cutout"
    assert [s["layout"] for s in c["scenes"]] == ["talk", "scene", "present", "end"]
    assert c["scenes"][0]["pose"] == "head_neutral" and c["scenes"][1]["card"] == "Night" and c["scenes"][2]["screen"] == "book.png"
    assert all("clip" not in s and "refs" not in s for s in c["scenes"]) and st["scenes"][1]["layout"] == "clip"      # the original is untouched
    from engine.story import CHAR_DIR
    assert all((CHAR_DIR / f"lumi_{s['pose']}.png").exists() for s in c["scenes"] if s["layout"] != "end")
