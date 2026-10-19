import io
import urllib.error

import pytest

from engine import linkedin
from engine.linkedin import LinkedInError, commentary, create_multi_image_post, escape_little, upload_image

TOKEN = "LI-SECRET-TOKEN"
PERSON = "urn:li:person:abc123"


class Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, token, *, json_body=None, data=None, headers=None):
        self.calls.append((method, url, json_body, data))
        if url.endswith("/rest/images?action=initializeUpload"):
            return 200, {}, {"value": {"uploadUrl": "https://upload.example/u1", "image": "urn:li:image:IMG1"}}
        if method == "PUT":
            return 201, {}, {}
        if url.endswith("/rest/posts"):
            return 201, {"x-restli-id": "urn:li:share:123"}, {}
        raise AssertionError(url)


def test_escape_little_escapes_every_reserved_character():
    assert escape_little("a|b{c}d@e[f]g(h)i<j>k#l\\m*n_o~p") == \
        "a\\|b\\{c\\}d\\@e\\[f\\]g\\(h\\)i\\<j\\>k\\#l\\\\m\\*n\\_o\\~p"
    assert escape_little("Plain words, a URL https://x.y/z?id=1&b=2") == "Plain words, a URL https://x.y/z?id=1&b=2"


def test_commentary_appends_hashtags_as_templates_and_enforces_the_length_limit():
    out = commentary("Hello (world)", ["#ScoreMyBiz", "#MSME"])
    assert out == "Hello \\(world\\)\n\n{hashtag|\\#|ScoreMyBiz} {hashtag|\\#|MSME}"
    with pytest.raises(LinkedInError):
        commentary("x" * 3001, [])


def test_upload_image_registers_then_puts_the_bytes(tmp_path, monkeypatch):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"JPEGDATA")
    fake = Fake()
    monkeypatch.setattr(linkedin, "call", fake)
    assert upload_image(TOKEN, PERSON, img) == "urn:li:image:IMG1"
    assert fake.calls[0][2] == {"initializeUploadRequest": {"owner": PERSON}}
    assert fake.calls[1][0] == "PUT" and fake.calls[1][1] == "https://upload.example/u1" and fake.calls[1][3] == b"JPEGDATA"


def test_multi_image_post_body_and_returned_urn(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(linkedin, "call", fake)
    urn = create_multi_image_post(TOKEN, PERSON, "text", ["urn:li:image:A", "urn:li:image:B"], ["alt a", "alt b"])
    assert urn == "urn:li:share:123"
    body = fake.calls[0][2]
    assert body["author"] == PERSON and body["commentary"] == "text"
    assert body["visibility"] == "PUBLIC" and body["lifecycleState"] == "PUBLISHED"
    assert body["distribution"]["feedDistribution"] == "MAIN_FEED"
    assert body["content"]["multiImage"]["images"] == [
        {"id": "urn:li:image:A", "altText": "alt a"}, {"id": "urn:li:image:B", "altText": "alt b"}]


def test_multi_image_needs_two_to_twenty_images():
    with pytest.raises(LinkedInError):
        create_multi_image_post(TOKEN, PERSON, "t", ["urn:li:image:A"], ["a"])
    with pytest.raises(LinkedInError):
        create_multi_image_post(TOKEN, PERSON, "t", [f"urn:li:image:{i}" for i in range(21)], ["a"] * 21)


def test_http_errors_never_leak_the_token(monkeypatch):
    def boom(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 401, "bad", {}, io.BytesIO(f"invalid {TOKEN}".encode()))
    monkeypatch.setattr(linkedin.urllib.request, "urlopen", boom)
    with pytest.raises(LinkedInError) as e:
        linkedin.call("GET", "https://api.linkedin.com/v2/userinfo", TOKEN)
    assert TOKEN not in str(e.value)


def test_requests_carry_the_version_and_protocol_headers(monkeypatch):
    seen = {}

    class Resp:
        status = 200
        headers = {}
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None, context=None):
        seen.update({k.lower(): v for k, v in req.header_items()})
        return Resp()
    monkeypatch.setattr(linkedin.urllib.request, "urlopen", fake_urlopen)
    linkedin.call("POST", "https://api.linkedin.com/rest/posts", TOKEN, json_body={"a": 1})
    assert seen["linkedin-version"] == linkedin.VERSION and seen["x-restli-protocol-version"] == "2.0.0"
    assert seen["authorization"] == "Bearer " + TOKEN and seen["content-type"] == "application/json"


def test_video_upload_initialises_puts_parts_in_order_finalises_with_etags_and_waits(tmp_path, monkeypatch):
    from engine.linkedin import upload_video
    vid = tmp_path / "v.mp4"; vid.write_bytes(b"A" * 5000000)   # two parts at 4 MiB
    calls = []
    def fake(method, url, token, *, json_body=None, data=None, headers=None):
        calls.append((method, url, json_body, len(data) if data else 0))
        if url.endswith("/rest/videos?action=initializeUpload"):
            assert json_body["initializeUploadRequest"]["owner"] == PERSON and json_body["initializeUploadRequest"]["fileSizeBytes"] == 5000000
            return 200, {}, {"value": {"video": "urn:li:video:V1", "uploadToken": "tok",
                   "uploadInstructions": [{"uploadUrl": "https://u/1", "firstByte": 0, "lastByte": 4194303},
                                          {"uploadUrl": "https://u/2", "firstByte": 4194304, "lastByte": 4999999}]}}
        if method == "PUT":
            return 200, {"etag": "e-" + url[-1]}, {}
        if url.endswith("/rest/videos?action=finalizeUpload"):
            assert json_body["finalizeUploadRequest"] == {"video": "urn:li:video:V1", "uploadToken": "tok", "uploadedPartIds": ["e-1", "e-2"]}
            return 200, {}, {}
        if "/rest/videos/" in url:
            return 200, {}, {"status": "AVAILABLE"}
        raise AssertionError(url)
    monkeypatch.setattr(linkedin, "call", fake)
    assert upload_video(TOKEN, PERSON, vid, sleep=lambda s: None) == "urn:li:video:V1"
    puts = [c for c in calls if c[0] == "PUT"]
    assert [c[3] for c in puts] == [4194304, 805696]


def test_video_post_body(monkeypatch):
    from engine.linkedin import create_video_post
    seen = {}
    def fake(method, url, token, *, json_body=None, data=None, headers=None):
        seen.update(body=json_body); return 201, {"x-restli-id": "urn:li:ugcPost:77"}, {}
    monkeypatch.setattr(linkedin, "call", fake)
    assert create_video_post(TOKEN, PERSON, "text", "urn:li:video:V1", "Friday") == "urn:li:ugcPost:77"
    assert seen["body"]["content"]["media"] == {"id": "urn:li:video:V1", "title": "Friday"}
    assert seen["body"]["author"] == PERSON and seen["body"]["lifecycleState"] == "PUBLISHED"


def test_single_image_post_uses_media_content_and_post_images_picks_single_or_multi(tmp_path, monkeypatch):
    fake = Fake()
    monkeypatch.setattr(linkedin, "call", fake)
    (tmp_path / "a.jpg").write_bytes(b"x"); (tmp_path / "b.jpg").write_bytes(b"y")
    urn = linkedin.post_images(TOKEN, PERSON, "Hook (one)", ["#SGLearning"], [tmp_path / "a.jpg"], ["Card one"])
    assert urn == "urn:li:share:123"
    post = [c for c in fake.calls if c[1].endswith("/rest/posts")][-1][2]
    assert post["content"] == {"media": {"id": "urn:li:image:IMG1", "altText": "Card one"}}
    assert post["commentary"] == "Hook \\(one\\)\n\n{hashtag|\\#|SGLearning}"
    linkedin.post_images(TOKEN, PERSON, "Two", [], [tmp_path / "a.jpg", tmp_path / "b.jpg"], ["one", "two"])
    post = [c for c in fake.calls if c[1].endswith("/rest/posts")][-1][2]
    assert [i["altText"] for i in post["content"]["multiImage"]["images"]] == ["one", "two"]
    with pytest.raises(LinkedInError):
        linkedin.post_images(TOKEN, PERSON, "None", [], [], [])


def test_multi_image_post_keeps_every_picture_when_alts_run_short(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(linkedin, "call", fake)
    create_multi_image_post(TOKEN, PERSON, "t", ["urn:li:image:1", "urn:li:image:2", "urn:li:image:3"], ["one"])
    post = [c for c in fake.calls if c[1].endswith("/rest/posts")][-1][2]
    assert [i["altText"] for i in post["content"]["multiImage"]["images"]] == ["one", "", ""]
