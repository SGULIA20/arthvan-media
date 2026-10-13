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
    cv2 = pytest.importorskip("cv2")
    im = cv2.imread(str(tmp_path / "fr" / "f0001.jpg"))
    assert im.shape[:2] == (1920, 1080)


def test_reference_pictures_change_the_key_and_reach_the_generator(tmp_path):
    ref = tmp_path / "mira.jpg"; ref.write_bytes(b"\xff\xd8mira")
    calls = []
    def gen(prompt, seconds, token, references=None): calls.append(references); return b"mp4"
    a = clip("mira at a window", cache=tmp_path / "c", ledger_path=tmp_path / "l.json", generate=gen, token="T", today=date(2026, 10, 13), library=tmp_path / "lib")
    b = clip("mira at a window", references=[ref], cache=tmp_path / "c", ledger_path=tmp_path / "l.json", generate=gen, token="T", today=date(2026, 10, 13), library=tmp_path / "lib")
    assert a != b and calls == [None, [ref]]
    idx = (tmp_path / "lib" / "index.md").read_text()
    assert "mira-at-a-window" in idx and "refs: mira.jpg" in idx and len(list((tmp_path / "lib").glob("*.mp4"))) == 2


def test_a_refused_reference_picture_falls_back_to_the_description_alone(tmp_path):
    from engine.broll import BRollBadReference
    ref = tmp_path / "f.jpg"; ref.write_bytes(b"\xff\xd8f")
    calls = []
    def gen(prompt, seconds, token, references=None):
        calls.append(references)
        if references: raise BRollBadReference("input image violates")
        return b"mp4"
    out = clip("the founder at a counter", references=[ref], cache=tmp_path / "c", ledger_path=tmp_path / "l.json", generate=gen, token="T", today=date(2026, 10, 13), library=tmp_path / "lib")
    assert out.exists() and calls == [[ref], None]


def test_call_retries_a_timeout_and_refreshes_the_token_on_401(monkeypatch):
    import urllib.error, io
    attempts = []
    class R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"ok": 1}'
    def fake_open(req, timeout=None, context=None):
        attempts.append(req.get_header("Authorization"))
        if len(attempts) == 1: raise TimeoutError("slow")
        if len(attempts) == 2: raise urllib.error.HTTPError(req.full_url, 401, "expired", {}, io.BytesIO(b"expired"))
        return R()
    monkeypatch.setattr(broll.urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(broll.time, "sleep", lambda s: None)
    tokens = iter(["T1", "T2"])
    monkeypatch.setattr(broll, "access_token", lambda: next(tokens))
    monkeypatch.setattr(broll.json, "load", lambda r: {"ok": 1})
    st, body = broll._call("GET", "https://x/y", broll._Token())
    assert st == 200 and attempts == ["Bearer T1", "Bearer T1", "Bearer T2"]
