import io
import json
import urllib.error
import urllib.parse

import pytest

from engine import facebook
from engine.facebook import FacebookError, post_reel, post_story

CFG = {"page_id": "PG1", "token": "TOK"}


class Resp:
    def __init__(self, obj): self.b = json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return self.b


class Net:
    """A fake Facebook: records every request and answers by URL."""
    def __init__(self, upload_status="complete", finish=None):
        self.calls, self.upload_status, self.finish = [], upload_status, finish or {"success": True, "post_id": "777"}

    def __call__(self, req, timeout=None, context=None):
        url, data, h = req.full_url, req.data, dict(req.header_items())
        self.calls.append((req.get_method(), url, data, h))
        if url.endswith("/PG1/video_reels") or url.endswith("/PG1/video_stories"):
            form = urllib.parse.parse_qs(data.decode())
            if form["upload_phase"] == ["start"]:
                return Resp({"video_id": "V9", "upload_url": "https://rupload.facebook.com/video-upload/v25.0/V9"})
            return Resp(self.finish)
        if "rupload.facebook.com" in url:
            return Resp({"success": True})
        if "/V9?" in url:
            return Resp({"status": {"video_status": "processing", "uploading_phase": {"status": self.upload_status}}})
        raise AssertionError("unexpected " + url)


@pytest.fixture
def video(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"; f.write_bytes(b"MP4DATA")
    monkeypatch.setattr(facebook, "duration_seconds", lambda p: 59.0)
    monkeypatch.setattr(facebook.time, "sleep", lambda s: None)
    return f


def test_a_reel_is_started_uploaded_from_disk_and_published_with_its_description(video, monkeypatch):
    net = Net(); monkeypatch.setattr(facebook.urllib.request, "urlopen", net)
    assert post_reel(CFG, video, "Caption https://play") == "777"
    start, upload, status, finish = net.calls[0], net.calls[1], net.calls[2], net.calls[3]
    assert start[1].endswith("/PG1/video_reels") and b"upload_phase=start" in start[2] and b"access_token=TOK" in start[2]
    assert upload[1] == "https://rupload.facebook.com/video-upload/v25.0/V9" and upload[2] == b"MP4DATA"
    hdr = {k.lower(): v for k, v in upload[3].items()}
    assert hdr["authorization"] == "OAuth TOK" and hdr["offset"] == "0" and hdr["file_size"] == "7"
    form = urllib.parse.parse_qs(finish[2].decode())
    assert form["upload_phase"] == ["finish"] and form["video_id"] == ["V9"] and form["video_state"] == ["PUBLISHED"] and form["description"] == ["Caption https://play"]


def test_a_story_uses_the_story_edge_and_sends_no_description(video, monkeypatch):
    net = Net(); monkeypatch.setattr(facebook.urllib.request, "urlopen", net)
    assert post_story(CFG, video) == "777"
    assert net.calls[0][1].endswith("/PG1/video_stories") and net.calls[-1][1].endswith("/PG1/video_stories")
    assert b"description" not in net.calls[-1][2] and b"video_state" not in net.calls[-1][2]


def test_it_waits_for_the_upload_to_finish_before_publishing(video, monkeypatch):
    states = iter(["in_progress", "in_progress", "complete"])
    net = Net()
    orig = net.__call__
    def flaky(req, timeout=None, context=None):
        if "/V9?" in req.full_url:
            net.calls.append((req.get_method(), req.full_url, None, {})); return Resp({"status": {"uploading_phase": {"status": next(states)}}})
        return orig(req, timeout, context)
    monkeypatch.setattr(facebook.urllib.request, "urlopen", flaky)
    assert post_reel(CFG, video, "c") == "777"
    assert sum("/V9?" in c[1] for c in net.calls) == 3 and net.calls[-1][1].endswith("/video_reels")


def test_stories_over_60_seconds_and_reels_over_90_are_refused_before_any_request(video, monkeypatch):
    net = Net(); monkeypatch.setattr(facebook.urllib.request, "urlopen", net)
    monkeypatch.setattr(facebook, "duration_seconds", lambda p: 61.0)
    with pytest.raises(FacebookError, match="Stories allow up to 60"):
        post_story(CFG, video)
    monkeypatch.setattr(facebook, "duration_seconds", lambda p: 95.0)
    with pytest.raises(FacebookError, match="Reels allow up to 90"):
        post_reel(CFG, video, "c")
    assert net.calls == []


def test_errors_never_contain_the_token_and_server_errors_are_retried(video, monkeypatch):
    n = {"n": 0}
    def fake(req, timeout=None, context=None):
        n["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 503 if n["n"] == 1 else 400, "x", {}, io.BytesIO(b'{"error":{"message":"Invalid token TOK"}}'))
    monkeypatch.setattr(facebook.urllib.request, "urlopen", fake)
    with pytest.raises(FacebookError) as e:
        post_reel(CFG, video, "c")
    assert "TOK" not in str(e.value) and "<token>" in str(e.value) and n["n"] == 2


def test_a_rejected_video_stops_before_publishing(video, monkeypatch):
    net = Net(upload_status="error"); monkeypatch.setattr(facebook.urllib.request, "urlopen", net)
    with pytest.raises(FacebookError, match="rejected the video"):
        post_story(CFG, video)
    assert not any(b"finish" in (c[2] or b"") for c in net.calls)
