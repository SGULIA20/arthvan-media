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
