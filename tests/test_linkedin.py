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
