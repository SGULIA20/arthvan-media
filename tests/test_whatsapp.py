import json

import pytest

from engine import whatsapp
from engine.whatsapp import WhatsAppError, WhatsAppNotReady, send_status_video

TEMPLATES = {"status": "success", "templates": [
    {"id": "T-OLD", "elementName": "daily_status_video", "status": "REJECTED", "languageCode": "en"},
    {"id": "T-HI", "elementName": "daily_status_video", "status": "APPROVED", "languageCode": "hi"},
    {"id": "T-EN", "elementName": "daily_status_video", "status": "APPROVED", "languageCode": "en"},
]}


class Fake:
    def __init__(self, fail_first_send=False, templates=TEMPLATES):
        self.calls, self.fail_first_send, self.sends, self.templates = [], fail_first_send, 0, templates

    def __call__(self, method, url, *, form=None, json_body=None, headers=None):
        self.calls.append((method, url, form, json_body, headers or {}))
        assert headers.get("apikey") == "KEY", "every call carries the app API key"
        if url.split("?")[0].endswith("/wa/app/APP1/template"):
            return 200, self.templates
        if url.endswith("/wa/api/v1/template/msg"):
            self.sends += 1
            if self.fail_first_send and self.sends == 1:
                return 500, {"status": "error", "message": "hiccup"}
            return 202, {"status": "success", "messageId": "gs-1"}
        raise AssertionError(url)


CFG = {"api_key": "KEY", "app_id": "APP1", "app_name": "scoremybizapp", "source": "+234 812 566 6665",
       "template": "daily_status_video", "to": "+234 812 000 0000"}


def test_sends_the_approved_english_template_with_video_header_app_name_and_caption(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(whatsapp, "call", fake)
    mid = send_status_video(CFG, "https://raw/x/reel.mp4", "ScoreMyBiz", "Know where your money is. scoremybiz.com")
    assert mid == "gs-1"
    form = [c for c in fake.calls if c[1].endswith("/template/msg")][0][2]
    assert form["destination"] == "2348120000000" and form["source"] == "2348125666665"
    assert form["src.name"] == "scoremybizapp" and form["channel"] == "whatsapp"
    assert json.loads(form["template"]) == {"id": "T-EN", "params": ["ScoreMyBiz", "Know where your money is. scoremybiz.com"]}
    assert json.loads(form["message"]) == {"type": "video", "video": {"link": "https://raw/x/reel.mp4"}}


def test_template_lookup_asks_only_for_approved_templates(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(whatsapp, "call", fake)
    send_status_video(CFG, "u", "Waypoint", "c")
    url = [c[1] for c in fake.calls if "/wa/app/APP1/template" in c[1]][0]
    assert "templateStatus=APPROVED" in url


def test_a_pending_template_is_a_clear_error(monkeypatch):
    fake = Fake(templates={"status": "success", "templates": [TEMPLATES["templates"][0]]})
    monkeypatch.setattr(whatsapp, "call", fake)
    with pytest.raises(WhatsAppNotReady, match="not approved yet"):
        send_status_video(CFG, "u", "a", "c")
    assert fake.sends == 0
    assert issubclass(WhatsAppNotReady, WhatsAppError)


def test_retries_the_send_once(monkeypatch):
    fake = Fake(fail_first_send=True)
    monkeypatch.setattr(whatsapp, "call", fake)
    assert send_status_video(CFG, "u", "Waypoint", "c") == "gs-1"
    assert fake.sends == 2


def test_errors_never_include_the_api_key(monkeypatch):
    def boom(method, url, **kw):
        return 401, {"message": "Authentication Failed for KEY"}
    monkeypatch.setattr(whatsapp, "call", boom)
    with pytest.raises(WhatsAppError) as e:
        send_status_video(CFG, "u", "a", "c")
    assert "KEY" not in str(e.value) and "<key>" in str(e.value)
