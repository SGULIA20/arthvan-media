import io
import json
import urllib.error

import pytest

from engine import telegram
from engine.telegram import TelegramError, find_chat_id, send_video


class Resp:
    def __init__(self, obj): self.b = json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return self.b


def test_send_video_posts_the_url_and_caption_and_returns_the_message_id(monkeypatch):
    seen = {}
    def fake(req, timeout=None, context=None):
        seen["url"] = req.full_url; seen["body"] = json.loads(req.data); return Resp({"ok": True, "result": {"message_id": 7}})
    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake)
    assert send_video({"token": "TOK", "chat_id": "9"}, "https://v/x.mp4", "c" * 2000) == "7"
    assert seen["url"].endswith("/botTOK/sendVideo") and seen["body"]["chat_id"] == "9" and seen["body"]["video"] == "https://v/x.mp4" and len(seen["body"]["caption"]) == 1000


def test_errors_never_contain_the_token_and_server_errors_are_retried(monkeypatch):
    calls = []
    def fake(req, timeout=None, context=None):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 400 if len(calls) > 1 else 503, "x", {}, io.BytesIO(b"bad token TOK"))
    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake); monkeypatch.setattr(telegram.time, "sleep", lambda s: None)
    with pytest.raises(TelegramError) as e:
        send_video({"token": "TOK", "chat_id": "9"}, "u", "c")
    assert "TOK" not in str(e.value) and "<token>" in str(e.value) and len(calls) == 2


def test_find_chat_id_takes_the_latest_conversation_and_explains_when_there_is_none(monkeypatch):
    monkeypatch.setattr(telegram, "_call", lambda token, method, body: {"result": [{"message": {"chat": {"id": 1}}}, {"message": {"chat": {"id": 2}}}]})
    assert find_chat_id("T") == "2"
    monkeypatch.setattr(telegram, "_call", lambda token, method, body: {"result": []})
    with pytest.raises(TelegramError, match="send the bot"):
        find_chat_id("T")
