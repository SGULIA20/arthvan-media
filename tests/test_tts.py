import wave
from pathlib import Path

import pytest

from engine import tts
from engine.tts import TTSError, gemini_clip, pick_voice


def _wav_bytes(seconds=1.0, rate=24000):
    import io
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(b"\0\0" * int(seconds * rate))
    return b.getvalue()


class FakeAPI:
    def __init__(self, fail_first=False):
        self.calls, self.fail_first = [], fail_first

    def __call__(self, model, text, voice, key):
        self.calls.append((model, text, voice, key))
        if self.fail_first and len(self.calls) == 1:
            return 503, {"error": {"message": "overloaded"}}
        return 200, {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/wav", "data": __import__("base64").b64encode(_wav_bytes(1.5)).decode()}}]}}],
                     "usageMetadata": {"candidatesTokenCount": 37}}


def test_gemini_clip_writes_a_44k_stereo_wav_and_returns_seconds(tmp_path, monkeypatch):
    fake = FakeAPI(); monkeypatch.setattr(tts, "_generate", fake)
    out = tmp_path / "vo0.wav"
    d = gemini_clip("नमस्ते, मैं लूमी हूँ।", "Kore", out, key="K", cache=tmp_path / "cache")
    assert abs(d - 1.5) < 0.05
    with wave.open(str(out)) as w:
        assert w.getnchannels() == 2 and w.getframerate() == 44100
    assert fake.calls[0][1].endswith("नमस्ते, मैं लूमी हूँ।") and fake.calls[0][2] == "Kore" and fake.calls[0][3] == "K"


def test_unchanged_lines_come_from_the_cache_without_a_second_call(tmp_path, monkeypatch):
    fake = FakeAPI(); monkeypatch.setattr(tts, "_generate", fake)
    for i in range(2):
        gemini_clip("same line", "Kore", tmp_path / f"vo{i}.wav", key="K", cache=tmp_path / "cache")
    gemini_clip("same line", "Puck", tmp_path / "vo9.wav", key="K", cache=tmp_path / "cache")   # another voice: new audio
    assert len(fake.calls) == 2


def test_a_transient_error_is_retried_once(tmp_path, monkeypatch):
    fake = FakeAPI(fail_first=True); monkeypatch.setattr(tts, "_generate", fake)
    monkeypatch.setattr(tts.time, "sleep", lambda s: None)
    assert gemini_clip("x", "Kore", tmp_path / "v.wav", key="K", cache=tmp_path / "c") > 0
    assert len(fake.calls) == 2


def test_missing_key_is_a_clear_error_before_any_call(tmp_path, monkeypatch):
    fake = FakeAPI(); monkeypatch.setattr(tts, "_generate", fake)
    with pytest.raises(TTSError, match="GEMINI_API_KEY"):
        gemini_clip("x", "Kore", tmp_path / "v.wav", key="", cache=tmp_path / "c")
    assert fake.calls == []


def test_each_character_has_a_fixed_gemini_voice():
    assert pick_voice({"character": "lumi"}) == "Kore"
    assert pick_voice({"character": "mira"}) == "Leda"
    assert pick_voice({"character": "founder_suit"}) == pick_voice({"character": "founder_casual"}) == "Charon"
    assert pick_voice({"character": "lumi", "voice": "Aoede"}) == "Aoede"       # explicit wins


def test_a_quota_error_is_waited_out_for_several_tries_and_a_real_error_is_not(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr(tts.time, "sleep", lambda s: waits.append(s))
    class Quota:
        def __init__(self): self.n = 0
        def __call__(self, model, text, voice, key):
            self.n += 1
            if self.n <= 3: return 429, {"error": {"message": "quota"}}
            return FakeAPI()(model, text, voice, key)
    q = Quota(); monkeypatch.setattr(tts, "_generate", q)
    assert gemini_clip("x", "Kore", tmp_path / "a.wav", key="K", cache=tmp_path / "c") > 0 and q.n == 4 and waits == [20, 35, 50]
    monkeypatch.setattr(tts, "_generate", lambda *a: (400, {"error": {"message": "bad"}}))
    with pytest.raises(TTSError, match="400"):
        gemini_clip("y", "Kore", tmp_path / "b.wav", key="K", cache=tmp_path / "c")


DAILY = {"error": {"message": "quota", "details": [
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]},
    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "15659s"}]}}
MINUTE = {"error": {"message": "quota", "details": [
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel"}]}]}}


def test_daily_quota_wait_reads_the_reset_time_and_ignores_per_minute_limits():
    assert tts.daily_quota_wait(DAILY) == 15659 + 60
    assert tts.daily_quota_wait(MINUTE) is None and tts.daily_quota_wait({"error": {"message": "quota"}}) is None


def test_a_used_up_daily_allowance_is_slept_through_without_using_the_retry_budget(tmp_path, monkeypatch):
    slept, calls = [], []
    monkeypatch.setattr(tts, "_wait_for_reset", lambda s: slept.append(s))
    monkeypatch.setattr(tts.time, "sleep", lambda s: None)
    def gen(model, text, voice, key):
        calls.append(1)
        return (429, DAILY) if len(calls) <= 2 else FakeAPI()(model, text, voice, key)
    monkeypatch.setattr(tts, "_generate", gen)
    assert gemini_clip("z", "Kore", tmp_path / "a.wav", key="K", cache=tmp_path / "c") > 0
    assert slept == [15719, 15719] and len(calls) == 3


def test_extra_voice_models_are_metered_and_stop_at_the_approved_amount(tmp_path, monkeypatch):
    from engine import tts
    monkeypatch.setattr(tts, "SPEND_FILE", tmp_path / "spend.json")
    monkeypatch.setattr(tts, "BACKUP_FILE", tmp_path / "models.json")
    (tmp_path / "models.json").write_text('{"backups": ["gemini-3.8-flash-tts"], "cap_inr": 1.0, "note": "test"}')
    usage = {"promptTokenCount": 30, "candidatesTokenCount": 1250}
    one = tts.cost_inr("gemini-3.8-flash-tts", usage)
    assert 2.0 < one < 2.6                                                    # about ₹2.2 for a 50-second Reel at the cautious rate
    assert tts.extra_spend() == 0.0 and tts.extra_cap() == 1.0
    tts.record_spend("gemini-3.8-flash-tts", usage)
    assert abs(tts.extra_spend() - one) < 1e-3
    pcm = b"\x00\x00" * 2400
    calls = []
    def fake_generate(model, text, voice, key):
        calls.append(model)
        import base64
        return 200, {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}], "usageMetadata": usage}
    monkeypatch.setattr(tts, "_generate", fake_generate)
    with pytest.raises(tts.TTSError, match="DAILY_VOICE_QUOTA"):
        tts.gemini_clip("hello", "Kore", tmp_path / "o.wav", key="k", cache=tmp_path / "c", model="gemini-3.8-flash-tts")       # already past the cap: no request is made
    assert calls == []


def test_an_empty_gemini_reply_is_asked_again_and_then_reported_plainly(tmp_path, monkeypatch):
    import base64
    from engine import tts
    monkeypatch.setattr(tts.time, "sleep", lambda s: None)
    pcm = b"\x00\x00" * 2400
    good = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]}
    empty = {"candidates": [{"finishReason": "OTHER"}]}
    replies = iter([(200, empty), (200, good)])
    monkeypatch.setattr(tts, "_generate", lambda *a: next(replies))
    assert tts.gemini_clip("hello", "Kore", tmp_path / "o.wav", key="k", cache=tmp_path / "c") > 0          # second answer has audio
    monkeypatch.setattr(tts, "_generate", lambda *a: (200, empty))
    with pytest.raises(tts.TTSError, match="no audio"):
        tts.gemini_clip("another line", "Kore", tmp_path / "o2.wav", key="k", cache=tmp_path / "c")


def test_a_cut_connection_is_retried_not_failed(tmp_path, monkeypatch):
    import base64, http.client
    from engine import tts
    monkeypatch.setattr(tts.time, "sleep", lambda s: None)
    pcm = b"\x00\x00" * 2400
    good = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]}
    replies = iter([(599, {"error": {"message": "connection interrupted: IncompleteRead"}}), (200, good)])
    monkeypatch.setattr(tts, "_generate", lambda *a: next(replies))
    assert tts.gemini_clip("hello", "Kore", tmp_path / "o.wav", key="k", cache=tmp_path / "c") > 0
