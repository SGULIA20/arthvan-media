import json
from pathlib import Path

from engine import illustrate as il

STORY = {"id": "demo-hi", "art": {"style": "STYLE.", "ref": ["mira_front_neutral.png"],
                                  "cast": {"Anaya": "Anaya has long hair.", "Maa": "Maa wears a blue saree.", "fox": "The fox is orange."}},
         "scenes": [{"layout": "talk"},
                    {"layout": "illus", "image": "s01.png", "art": "Anaya talks to Maa in a kitchen."},
                    {"layout": "illus", "image": "s02.png", "art": "A rooftop at night.", "noref": True},
                    {"layout": "phone", "screen": "x.png"}]}


def test_the_prompt_has_the_style_only_the_cast_named_in_the_scene_and_no_text_rule():
    p = il.compose_prompt(STORY["art"], "Anaya talks to Maa in a kitchen.")
    assert p.startswith("STYLE.") and "Anaya has long hair." in p and "Maa wears a blue saree." in p and "fox is orange" not in p
    assert "No text" in p and p.index("Anaya has long hair.") < p.index("Scene:")


def test_each_scene_with_an_art_line_is_drawn_once_and_a_picture_that_exists_is_never_paid_for_again(tmp_path):
    calls = []
    def fake(prompt, out, refs, model):
        calls.append((out.name, [Path(r).name for r in refs])); out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(b"png")
    made = il.make_story_art(STORY, root=tmp_path, gen=fake)
    assert [m.name for m in made] == ["s01.png", "s02.png"]
    assert calls == [("s01.png", ["mira_front_neutral.png"]), ("s02.png", [])]          # the reference only where the scene does not say noref
    assert il.make_story_art(STORY, root=tmp_path, gen=fake) == [] and len(calls) == 2    # second run: nothing drawn, nothing paid
    assert il.make_story_art(STORY, only=[1], root=tmp_path, gen=fake) == []


def test_every_picture_is_counted_in_the_spend_file(tmp_path):
    f = tmp_path / "spend.json"
    il.record_spend("gemini-2.5-flash-image", f); total = il.record_spend("gemini-2.5-flash-image", f)
    d = json.loads(f.read_text())
    assert total == 8.0 and d["images"] == 2 and d["by_model"] == {"gemini-2.5-flash-image": 2}


def test_a_story_cannot_be_rendered_before_its_pictures_are_drawn(tmp_path):
    from engine.story import missing_pictures
    story = {"id": "demo-hi", "app": "waypoint", "character": "mira", "lang": "hi-IN", "scenes": [{"layout": "illus", "image": "s01.png"}]}
    assert "illustration s01.png not drawn yet" in missing_pictures(story, tmp_path)[0]
    (tmp_path / "stories" / "art" / "demo-hi").mkdir(parents=True); (tmp_path / "stories" / "art" / "demo-hi" / "s01.png").write_bytes(b"x")
    assert missing_pictures(story, tmp_path) == []


def test_the_pause_after_each_voice_line_can_be_shortened_per_story():
    from engine.story import speed_for
    assert speed_for([3.0] * 15, [2.2] * 15, pad=0.4) == 1.0 and speed_for([3.0] * 15, [2.2] * 15, pad=1.2) > 1.0
