import json
from datetime import date
from pathlib import Path

import pytest

from engine import broll
from engine.broll import BRollError, clip, key_for, pace, spent_inr, status_line


def test_clip_is_generated_once_cached_and_charged_to_the_month(tmp_path):
    calls = []
    gen = lambda prompt, seconds, token: calls.append((prompt, seconds, token)) or b"mp4bytes"
    p = clip("a shop at closing time", cache=tmp_path / "c", ledger_path=tmp_path / "l.json", generate=gen, token="T", today=date(2026, 10, 12))
    assert p.read_bytes() == b"mp4bytes" and p.name == key_for("a shop at closing time", 8) + ".mp4"
    assert calls[0][0].startswith("Cinematic") and "closing time" in calls[0][0] and calls[0][1] == 8
    clip("a shop at closing time", cache=tmp_path / "c", ledger_path=tmp_path / "l.json", generate=gen, token="T", today=date(2026, 10, 12))
    assert len(calls) == 1
    assert spent_inr(tmp_path / "l.json") == 8 * broll.INR_PER_SECOND
    led = json.loads((tmp_path / "l.json").read_text()); assert led["seconds"] == 8 and led["shots"][0]["day"] == "2026-10-12"


def test_the_credit_stop_blocks_generation_but_not_cached_clips(tmp_path):
    (tmp_path / "l.json").write_text(json.dumps({"spent_inr": 27950.0}))
    gen = lambda *a: b"x"
    with pytest.raises(BRollError, match="credit is finished"):
        clip("new shot", cache=tmp_path / "c", ledger_path=tmp_path / "l.json", generate=gen, token="T", today=date(2026, 10, 20))
    (tmp_path / "c").mkdir(exist_ok=True); (tmp_path / "c" / (key_for("old shot", 8) + ".mp4")).write_bytes(b"cached")
    assert clip("old shot", cache=tmp_path / "c", ledger_path=tmp_path / "l.json", generate=gen, token="T", today=date(2026, 10, 20)).read_bytes() == b"cached"


def test_nothing_is_generated_after_the_deadline(tmp_path):
    with pytest.raises(BRollError, match="expired"):
        clip("x", cache=tmp_path / "c", ledger_path=tmp_path / "l.json", generate=lambda *a: b"x", token="T", today=date(2026, 12, 11))


def test_pace_and_status_line_follow_the_plan_to_finish_by_10_dec(tmp_path):
    (tmp_path / "l.json").write_text(json.dumps({"spent_inr": 7000.0}))
    p = pace(tmp_path / "l.json", date(2026, 11, 10))           # roughly half way between 12 Oct and 10 Dec
    assert 13000 <= p["target_inr"] <= 15000 and p["spent_inr"] == 7000 and p["days_left"] == 30 and not p["finished"]
    assert "₹7000 used of ₹28000" in status_line(tmp_path / "l.json", date(2026, 11, 10))
    (tmp_path / "l.json").write_text(json.dumps({"spent_inr": 28000.0}))
    assert "FINISHED" in status_line(tmp_path / "l.json", date(2026, 11, 10))


def test_frames_cover_crop_to_the_story_canvas(tmp_path):
    import subprocess
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=720x1280:d=1", "-r", "24", str(src)], check=True)
    n = broll.frames(src, tmp_path / "fr", fps=30)
    assert n in (30, 31)
    import cv2
    im = cv2.imread(str(tmp_path / "fr" / "f0001.jpg"))
    assert im.shape[:2] == (1920, 1080)
