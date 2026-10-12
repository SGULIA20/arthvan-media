import json
import numpy as np
import cv2
import pytest

from engine import poses
from engine.poses import PoseError, cutout, make_pose, missing


def _picture():
    img = np.full((120, 100, 3), 255, np.uint8)                      # white background
    cv2.circle(img, (50, 60), 30, (40, 60, 200), -1)                  # the character (red-ish)
    cv2.circle(img, (50, 60), 8, (255, 255, 255), -1)                 # a white "shirt" patch inside
    return img


def test_cutout_keeps_enclosed_white_but_drops_the_background():
    a = cutout(_picture())[:, :, 3]
    assert a[5, 5] == 0 and a[115, 95] == 0           # corners are background
    assert a[60, 50] > 200                            # the white patch inside the character stays
    assert a[60, 30] > 200 and a[60, 95] == 0


def test_make_pose_generates_once_cuts_out_and_keeps_the_source(tmp_path):
    calls = []
    def fake_generate(prompt, reference, key):
        calls.append(prompt); ok, buf = cv2.imencode(".jpg", _picture()); return buf.tobytes()
    ref = tmp_path / "ref.jpg"; ref.write_bytes(b"\xff\xd8ref")
    out = make_pose("founder_suit", "thinking", "hand on chin", reference=ref, key="K", generate=fake_generate,
                    out_dir=tmp_path / "chars", source_dir=tmp_path / "src")
    assert out.name == "founder_suit_thinking.png" and out.exists()
    assert (tmp_path / "src" / "founder" / "founder_suit_thinking.jpg").exists()
    assert cv2.imread(str(out), cv2.IMREAD_UNCHANGED).shape[2] == 4
    assert "hand on chin" in calls[0] and "white background" in calls[0]
    make_pose("founder_suit", "thinking", "hand on chin", reference=ref, key="K", generate=fake_generate, out_dir=tmp_path / "chars", source_dir=tmp_path / "src")
    assert len(calls) == 1                                            # never paid for twice


def test_missing_lists_only_poses_without_a_png(tmp_path):
    (tmp_path / "lumi_kurta_phone.png").write_bytes(b"x")
    cat = {"lumi_kurta": {"phone": "p", "front_happy": "q"}, "founder_suit": {"thinking": "r"}}
    assert [(c, p) for c, p, _ in missing(cat, tmp_path)] == [("lumi_kurta", "front_happy"), ("founder_suit", "thinking")]


def test_no_key_is_a_clear_error(tmp_path):
    with pytest.raises(PoseError, match="GEMINI_API_KEY"):
        make_pose("founder_suit", "x", "p", reference=tmp_path, key="", generate=lambda *a: b"", out_dir=tmp_path)


def test_catalogue_is_valid_and_names_real_characters():
    cat = json.loads(poses.CATALOGUE.read_text())
    assert all(c.split("_")[0] in {"founder", "lumi", "mira"} for c in cat)       # every costume belongs to a real character
    assert all(isinstance(p, str) and len(p) > 10 for poses_ in cat.values() for p in poses_.values())
