import io
import json
import urllib.error

import pytest

from engine import telegram
from engine.telegram import TelegramError, find_chat_id, send_message, send_video, send_video_file


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


def test_send_message_trims_to_telegrams_limit(monkeypatch):
    seen = {}
    def fake(req, timeout=None, context=None):
        seen["body"] = json.loads(req.data); seen["url"] = req.full_url; return Resp({"ok": True, "result": {"message_id": 3}})
    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake)
    assert send_message({"token": "TOK", "chat_id": "9"}, "x" * 6000) == "3"
    assert seen["url"].endswith("/botTOK/sendMessage") and len(seen["body"]["text"]) == 4000


def test_send_video_file_uploads_the_bytes_as_multipart(monkeypatch, tmp_path):
    f = tmp_path / "a.mp4"; f.write_bytes(b"VIDEOBYTES")
    seen = {}
    def fake(req, timeout=None, context=None):
        seen["ct"] = req.get_header("Content-type"); seen["data"] = req.data; return Resp({"ok": True, "result": {"message_id": 5}})
    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake)
    assert send_video_file({"token": "TOK", "chat_id": "9"}, f, "cap") == "5"
    assert seen["ct"].startswith("multipart/form-data; boundary=") and b"VIDEOBYTES" in seen["data"] and b'name="chat_id"' in seen["data"] and b"cap" in seen["data"]
