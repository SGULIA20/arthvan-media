import io
import json
import urllib.error

import pytest

from engine import youtube
from engine.youtube import YouTubeError, access_token, build_metadata, upload_short


def test_metadata_has_shorts_tag_play_link_and_safe_defaults():
    m = build_metadata("Friday", "Meena's week, told by Lumi.", "https://play.google.com/store/apps/details?id=com.scoremybiz.app", ["Lumi", "ScoreMyBiz"])
    assert m["snippet"]["title"].endswith("#Shorts") and len(m["snippet"]["title"]) <= 100
    assert "play.google.com" in m["snippet"]["description"] and "Lumi" in m["snippet"]["tags"]
    assert m["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    assert m["snippet"]["categoryId"] == "22"


def test_title_is_truncated_to_youtube_limit():
    m = build_metadata("x" * 150, "d", "https://p", [])
    assert len(m["snippet"]["title"]) <= 100 and m["snippet"]["title"].endswith("#Shorts")


def test_access_token_exchanges_the_refresh_token(monkeypatch):
    seen = {}
    def fake_post(url, form):
        seen.update(url=url, form=form); return {"access_token": "AT", "expires_in": 3599}
    assert access_token("CID", "SEC", "RT", post=fake_post) == "AT"
    assert seen["url"] == "https://oauth2.googleapis.com/token" and seen["form"]["grant_type"] == "refresh_token"
    with pytest.raises(YouTubeError):
        access_token("CID", "SEC", "RT", post=lambda u, f: {"error": "invalid_grant"})


def test_upload_short_initiates_resumable_session_then_puts_bytes(tmp_path, monkeypatch):
    vid = tmp_path / "v.mp4"; vid.write_bytes(b"A" * 1000)
    calls = []
    def fake_call(method, url, token, *, json_body=None, data=None, headers=None):
        calls.append((method, url, json_body, len(data) if data else 0, headers or {}))
        if "uploadType=resumable" in url:
            assert json_body["snippet"]["title"].endswith("#Shorts")
            return 200, {"location": "https://upload.example/session"}, {}
        if method == "PUT":
            return 200, {}, {"id": "VID123", "status": {"privacyStatus": "public"}}
        raise AssertionError(url)
    monkeypatch.setattr(youtube, "call", fake_call)
    vid_id = upload_short("AT", vid, build_metadata("t", "d", "https://p", []))
    assert vid_id == "VID123"
    assert calls[1][0] == "PUT" and calls[1][1] == "https://upload.example/session" and calls[1][3] == 1000
    assert calls[1][4].get("Content-Type") == "video/mp4"


def test_http_errors_never_leak_the_token(monkeypatch):
    def boom(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 403, "f", {}, io.BytesIO(b"quotaExceeded SECRET-AT"))
    monkeypatch.setattr(youtube.urllib.request, "urlopen", boom)
    with pytest.raises(YouTubeError) as e:
        youtube.call("GET", "https://www.googleapis.com/youtube/v3/channels?mine=true", "SECRET-AT")
    assert "SECRET-AT" not in str(e.value)
