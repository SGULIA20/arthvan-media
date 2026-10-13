import io
import urllib.error

import pytest

from engine import threads
from engine.threads import ThreadsError, post_carousel, refresh_token

TOKEN = "TH-SECRET"
UID = "9001"


class Fake:
    def __init__(self, statuses=None):
        self.calls, self.n, self.statuses = [], 0, statuses or {}

    def __call__(self, method, path, token, params=None):
        self.calls.append((method, path, dict(params or {})))
        if method == "POST" and path.endswith("/threads"):
            self.n += 1
            return {"id": f"c{self.n}"}
        if method == "GET":
            seq = self.statuses.get(path.strip("/"))
            return {"status": seq.pop(0) if seq else "FINISHED"}
        if path.endswith("/threads_publish"):
            return {"id": "post-" + params["creation_id"]}
        raise AssertionError(path)

    def posts(self, suffix):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith(suffix)]


def run(fake, monkeypatch, urls=("https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg"), text="hello", **kw):
    monkeypatch.setattr(threads, "call", fake)
    return post_carousel(UID, TOKEN, list(urls), text, sleep=lambda s: None, **kw)


def test_carousel_items_then_container_then_publish(monkeypatch):
    fake = Fake()
    assert run(fake, monkeypatch) == "post-c4"
    items = [c[2] for c in fake.posts("/threads")]
    assert all(i["media_type"] == "IMAGE" and i["is_carousel_item"] == "true" for i in items[:3])
    assert items[3] == {"media_type": "CAROUSEL", "children": "c1,c2,c3", "text": "hello"}
    assert fake.posts("/threads_publish")[0][2] == {"creation_id": "c4"}


def test_nothing_published_when_any_container_errors(monkeypatch):
    fake = Fake(statuses={"c2": ["IN_PROGRESS", "ERROR"]})
    with pytest.raises(ThreadsError):
        run(fake, monkeypatch)
    assert not fake.posts("/threads_publish")


def test_text_over_500_characters_is_refused_before_any_call(monkeypatch):
    fake = Fake()
    with pytest.raises(ThreadsError):
        run(fake, monkeypatch, text="x" * 501)
    assert fake.calls == []


def test_needs_two_to_twenty_images(monkeypatch):
    fake = Fake()
    with pytest.raises(ThreadsError):
        run(fake, monkeypatch, urls=["https://x/1.jpg"])
    assert fake.calls == []


def test_refresh_uses_the_threads_grant_type(monkeypatch):
    seen = {}

    def fake(method, path, token, params=None):
        seen.update(path=path, params=params)
        return {"access_token": "NEW", "expires_in": 5184000}
    monkeypatch.setattr(threads, "call", fake)
    assert refresh_token(TOKEN)["access_token"] == "NEW"
    assert seen["path"].endswith("/refresh_access_token") and seen["params"]["grant_type"] == "th_refresh_token"


def test_http_errors_never_leak_the_token(monkeypatch):
    def boom(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(f"bad {TOKEN}".encode()))
    monkeypatch.setattr(threads.urllib.request, "urlopen", boom)
    with pytest.raises(ThreadsError) as e:
        threads.call("GET", "/me", TOKEN)
    assert TOKEN not in str(e.value)


def test_post_video_creates_waits_for_the_video_and_publishes(monkeypatch):
    from engine.threads import post_video
    fake = Fake(statuses={"c1": ["IN_PROGRESS", "FINISHED"]})
    monkeypatch.setattr(threads, "call", fake)
    assert post_video(UID, TOKEN, "https://v/x.mp4", "text", sleep=lambda s: None) == "post-c1"
    created = fake.posts("/threads")[0][2]
    assert created["media_type"] == "VIDEO" and created["video_url"] == "https://v/x.mp4" and created["text"] == "text"
    with pytest.raises(ThreadsError, match="500"):
        post_video(UID, TOKEN, "u", "x" * 501, sleep=lambda s: None)
