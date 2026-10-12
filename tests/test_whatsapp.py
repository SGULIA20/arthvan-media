import pytest

from engine import whatsapp
from engine.whatsapp import WhatsAppError, send_status_video


class Fake:
    def __init__(self, fail_first_send=False):
        self.calls, self.fail_first_send, self.sends = [], fail_first_send, 0

    def __call__(self, method, url, *, form=None, json_body=None, headers=None):
        self.calls.append((method, url, form, json_body, headers or {}))
        if url.endswith("/account/login"):
            assert form == {"email": "e@x", "secret": "S"}
            return 200, {"token": "PARTNER"}
        if url.endswith("/app/APP1/token"):
            assert headers.get("Authorization") == "PARTNER"
            return 200, {"token": {"token": "APPTOK"}}
        if url.endswith("/app/APP1/v3/message"):
            self.sends += 1
            if self.fail_first_send and self.sends == 1:
                return 401, {"message": "revoked"}
            assert headers.get("Authorization") == "APPTOK"
            return 200, {"messages": [{"id": "wamid.1"}]}
        raise AssertionError(url)


CFG = {"app_id": "APP1", "email": "e@x", "secret": "S", "template": "daily_status_video", "to": "+234 812 000 0000"}


def test_sends_a_video_header_template_with_app_name_and_caption(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(whatsapp, "call", fake)
    mid = send_status_video(CFG, "https://raw/x/reel.mp4", "ScoreMyBiz", "Know where your money is. scoremybiz.com")
    assert mid == "wamid.1"
    body = [c for c in fake.calls if c[1].endswith("/v3/message")][0][3]
    assert body["to"] == "2348120000000" and body["type"] == "template"
    t = body["template"]; assert t["name"] == "daily_status_video" and t["language"]["code"] == "en"
    assert t["components"][0] == {"type": "header", "parameters": [{"type": "video", "video": {"link": "https://raw/x/reel.mp4"}}]}
    assert t["components"][1]["parameters"] == [{"type": "text", "text": "ScoreMyBiz"}, {"type": "text", "text": "Know where your money is. scoremybiz.com"}]


def test_retries_once_with_a_fresh_app_token_on_401(monkeypatch):
    fake = Fake(fail_first_send=True)
    monkeypatch.setattr(whatsapp, "call", fake)
    assert send_status_video(CFG, "https://raw/x/reel.mp4", "Waypoint", "c") == "wamid.1"
    assert fake.sends == 2 and sum(1 for c in fake.calls if c[1].endswith("/account/login")) == 2


def test_errors_never_include_the_secret(monkeypatch):
    def boom(method, url, **kw):
        return 500, {"message": "server says S and APPTOK"}
    monkeypatch.setattr(whatsapp, "call", boom)
    with pytest.raises(WhatsAppError) as e:
        send_status_video(CFG, "u", "a", "c")
    assert "S and" not in str(e.value) or "<secret>" in str(e.value)
