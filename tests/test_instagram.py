import io
import urllib.error

import pytest

from engine import instagram
from engine.instagram import Captions, InstagramError, PartialPublish, SetUrls, prepare_set, publish_set, refresh_token

TOKEN = "SECRET-TOKEN-123"
URLS = SetUrls(slides=["https://x/s1.jpg", "https://x/s2.jpg", "https://x/s3.jpg"], reel="https://x/r.mp4", story="https://x/r.mp4")
CAPS = Captions(post="post caption", reel="reel caption")


class Fake:
    def __init__(self, statuses=None):
        self.calls, self.n = [], 0
        self.statuses = statuses or {}

    def __call__(self, method, path, token, params=None):
        self.calls.append((method, path, dict(params or {})))
        if method == "POST" and path.endswith("/media"):
            self.n += 1
            return {"id": f"c{self.n}"}
        if method == "GET":
            cid = path.strip("/")
            seq = self.statuses.get(cid)
            return {"status_code": seq.pop(0) if seq else "FINISHED"}
        if path.endswith("/media_publish"):
            return {"id": "m-" + params["creation_id"]}
        raise AssertionError(path)

    def posts(self, suffix):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith(suffix)]


def run_prepare(fake, monkeypatch, **kw):
    monkeypatch.setattr(instagram, "call", fake)
    return prepare_set("17841", TOKEN, URLS, CAPS, sleep=lambda s: None, **kw)


def test_prepare_builds_carousel_reel_and_story_containers(monkeypatch):
    fake = Fake()
    prepared = run_prepare(fake, monkeypatch)
    media = [c[2] for c in fake.posts("/media")]
    assert [m.get("is_carousel_item") for m in media[:3]] == ["true"] * 3
    carousel = media[3]
    assert carousel["media_type"] == "CAROUSEL" and carousel["children"] == "c1,c2,c3" and carousel["caption"] == "post caption"
    reel = media[4]
    assert reel["media_type"] == "REELS" and reel["video_url"] == "https://x/r.mp4"
    assert reel["caption"] == "reel caption" and reel["share_to_feed"] == "true" and reel["thumb_offset"] == "2000"
    story = media[5]
    assert story["media_type"] == "STORIES" and "caption" not in story
    assert (prepared.post, prepared.reel, prepared.story) == ("c4", "c5", "c6")
    assert not fake.posts("/media_publish")


def test_nothing_is_published_when_a_container_errors(monkeypatch):
    fake = Fake(statuses={"c5": ["IN_PROGRESS", "ERROR"]})
    with pytest.raises(InstagramError):
        run_prepare(fake, monkeypatch)
    assert not fake.posts("/media_publish")


def test_waits_through_in_progress_then_times_out(monkeypatch):
    fake = Fake(statuses={"c5": ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]})
    run_prepare(fake, monkeypatch)  # finishes after waiting
    stuck = Fake(statuses={"c5": ["IN_PROGRESS"] * 50})
    with pytest.raises(InstagramError, match="never finished"):
        run_prepare(stuck, monkeypatch, max_polls=5)
    assert not stuck.posts("/media_publish")


def test_publish_order_is_post_reel_story(monkeypatch):
    fake = Fake()
    prepared = run_prepare(fake, monkeypatch)
    ids = publish_set("17841", TOKEN, prepared)
    assert [c[2]["creation_id"] for c in fake.posts("/media_publish")] == ["c4", "c5", "c6"]
    assert list(ids) == ["post", "reel", "story"]


def test_http_errors_never_leak_the_token(monkeypatch):
    def boom(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(f"bad token {TOKEN}".encode()))
    monkeypatch.setattr(instagram.urllib.request, "urlopen", boom)
    with pytest.raises(InstagramError) as e:
        instagram.call("GET", "/me", TOKEN, {"access_token": TOKEN})
    assert TOKEN not in str(e.value)


def test_refresh_token_calls_the_refresh_endpoint(monkeypatch):
    seen = {}

    def fake(method, path, token, params=None):
        seen.update(method=method, path=path, params=params)
        return {"access_token": "NEW", "expires_in": 5184000}
    monkeypatch.setattr(instagram, "call", fake)
    out = refresh_token(TOKEN)
    assert seen["path"].endswith("/refresh_access_token") and seen["params"]["grant_type"] == "ig_refresh_token"
    assert out == {"access_token": "NEW", "expires_in": 5184000}


def test_publish_failure_reports_what_was_already_published(monkeypatch):
    fake = Fake()
    prepared = run_prepare(fake, monkeypatch)

    def failing(method, path, token, params=None):
        if path.endswith("/media_publish") and params["creation_id"] == "c5":
            raise InstagramError("reel failed")
        return fake(method, path, token, params)
    monkeypatch.setattr(instagram, "call", failing)
    with pytest.raises(PartialPublish) as e:
        publish_set("17841", TOKEN, prepared)
    assert e.value.ids == {"post": "m-c4"}
