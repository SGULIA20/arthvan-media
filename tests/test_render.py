import subprocess
from datetime import date

import pytest

from engine.config import load_apps, load_bank
from engine.render import render_set, verify_image, verify_set
from engine.select_item import Selection

APPS = load_apps()


def sel_for(app, index=0):
    bank = load_bank(app)
    return Selection(app=app, item=bank[index], bank_index=index, day=date(2026, 10, 11))


@pytest.mark.slow
@pytest.mark.parametrize("app", ["waypoint", "scoremybiz"])
def test_render_set_makes_valid_post_slides_and_a_reel_with_music(app, tmp_path):
    rs = render_set(sel_for(app), APPS[app], tmp_path)
    n_slides = len(sel_for(app).item["slides"]) + 1  # plus the end card
    assert len(rs.slides) == n_slides
    assert all(p.suffix == ".jpg" and p.exists() for p in rs.slides)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height", "-show_entries", "format=duration",
         "-of", "default=nw=1", str(rs.reel)], capture_output=True, text=True, check=True).stdout
    assert "codec_name=h264" in probe and "codec_name=aac" in probe
    assert "width=1080" in probe and "height=1920" in probe
    assert 15.0 <= rs.seconds <= 30.0
    assert verify_set(rs) == []


@pytest.mark.slow
def test_different_templates_look_different(tmp_path):
    a = render_set(sel_for("scoremybiz", 0), APPS["scoremybiz"], tmp_path / "a")
    b = render_set(sel_for("scoremybiz", 1), APPS["scoremybiz"], tmp_path / "b")
    assert a.slides[0].read_bytes() != b.slides[0].read_bytes()


def test_verify_image_flags_a_blank_picture(tmp_path):
    blank = tmp_path / "blank.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1350",
                    "-frames:v", "1", str(blank)], check=True)
    assert verify_image(blank, 1080, 1350)
    ok = tmp_path / "noise.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=1080x1350",
                    "-frames:v", "1", str(ok)], check=True)
    assert verify_image(ok, 1080, 1350) == []
    assert verify_image(ok, 1080, 1920)  # wrong size is reported
