"""Voices from Gemini text-to-speech (any Indian language, male and female voices), with a local cache so a
re-render of unchanged lines costs nothing. Key: GEMINI_API_KEY in the environment or ~/arthvan-social/.env."""
import base64
import hashlib
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

from .config import ROOT

MODEL = "gemini-3.8-flash-lite-tts"
CACHE = ROOT / "stories" / "cache"
# one fixed voice per character so a character always sounds like itself, whatever the language
VOICES = {"lumi": "Kore", "mira": "Leda", "founder_suit": "Charon", "founder_casual": "Charon"}
STYLE = ""   # no spoken instruction: the model read it aloud and doubled every scene
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class TTSError(Exception):
    pass


MAX_DAILY_WAIT = 9 * 3600
WAIT_NOTE = Path.home() / "arthvan-social" / "logs" / "tts-wait.json"      # read by the live status page


# ---- spend meter for the EXTRA (non-default) voice models: the founder approved ₹400 on 15 Oct 2026 ----
SPEND_FILE = Path.home() / "arthvan-social" / "logs" / "voice-spend.json"
BACKUP_FILE = Path.home() / "arthvan-social" / "logs" / "voice-models.json"          # {"backups": [...], "cap_inr": 400}: exists only while the founder approves them
INR_PER_USD = 90.0                                                                   # a little above the real rate: the meter should overstate, never understate
# US dollars per million tokens (input, audio output). The 3.8 rate is an unconfirmed third-party figure, so it carries the higher 3.1 price.
RATES = {"gemini-3.8-flash-tts": (1.0, 20.0), "gemini-3.1-flash-tts-preview": (1.0, 20.0),
         "gemini-2.5-flash-preview-tts": (0.5, 10.0), "gemini-2.5-pro-preview-tts": (1.0, 20.0)}


def cost_inr(model: str, usage: dict) -> float:
    rin, rout = RATES.get(model, (1.0, 20.0))
    return ((usage.get("promptTokenCount") or 0) * rin + (usage.get("candidatesTokenCount") or 0) * rout) / 1e6 * INR_PER_USD


def _spend_read(path: Path = None) -> dict:
    try:
        return json.loads(Path(path or SPEND_FILE).read_text())
    except (OSError, ValueError):
        return {"inr": 0.0, "requests": 0}


def extra_spend(path: Path = None) -> float:
    return float(_spend_read(path).get("inr", 0.0))


def extra_cap(path: Path = None) -> float:
    try:
        return float(json.loads(Path(path or BACKUP_FILE).read_text()).get("cap_inr", 0.0))
    except (OSError, ValueError):
        return 0.0


def record_spend(model: str, usage: dict, path: Path = None) -> float:
    import fcntl
    path = Path(path or SPEND_FILE); path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = _spend_read(path)
        d["inr"] = round(float(d.get("inr", 0.0)) + cost_inr(model, usage), 4); d["requests"] = int(d.get("requests", 0)) + 1
        d.setdefault("by_model", {}); d["by_model"][model] = round(d["by_model"].get(model, 0.0) + cost_inr(model, usage), 4)
        path.write_text(json.dumps(d))
        return d["inr"]


def daily_quota_wait(body) -> "float | None":
    """Seconds until Google's PER-DAY voice allowance resets (plus a minute), or None when the 429 is only a per-minute limit."""
    daily, delay = False, None
    for d in ((body or {}).get("error") or {}).get("details", []):
        kind = str(d.get("@type", ""))
        if kind.endswith("QuotaFailure"):
            daily = daily or any("PerDay" in str(v.get("quotaId", "")) for v in d.get("violations", []))
        elif kind.endswith("RetryInfo"):
            try:
                delay = float(str(d.get("retryDelay", "")).rstrip("s"))
            except ValueError:
                pass
    return None if not daily else (delay if delay is not None else 6 * 3600.0) + 60


def _wait_for_reset(seconds: float) -> None:
    """Sleep in short steps by the wall clock (a sleeping Mac must not stretch the wait), leaving a note for the status page."""
    until = time.time() + seconds
    try:
        WAIT_NOTE.parent.mkdir(parents=True, exist_ok=True)
        WAIT_NOTE.write_text(json.dumps({"until": until, "text": "Google's daily voice allowance is used up"}))
    except OSError:
        pass
    print(f"Gemini voice allowance for today is used up; waiting {seconds / 3600:.1f} h for it to reset", flush=True)
    while time.time() < until:
        time.sleep(min(30, max(1, until - time.time())))
    try:
        WAIT_NOTE.unlink()
    except OSError:
        pass


def api_key(env=None) -> str:
    env = os.environ if env is None else env
    if env.get("GEMINI_API_KEY"):
        return env["GEMINI_API_KEY"]
    dotenv = Path.home() / "arthvan-social" / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def pick_voice(story: dict) -> str:
    return story.get("voice") if story.get("voice") in _all_voices() else VOICES.get(story.get("character", ""), "Kore")


def _all_voices():
    return {"Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe", "Autonoe", "Enceladus", "Iapetus",
            "Umbriel", "Algieba", "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar", "Alnilam", "Schedar",
            "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi", "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat"}


def _generate(model: str, text: str, voice: str, key: str):
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": {"message": raw[:200]}}


def gemini_clip(text: str, voice: str, out_wav: Path, *, key: str = None, cache: Path = CACHE, model: str = None) -> float:
    """Speak `text` with `voice` into out_wav (44.1 kHz stereo, like the macOS path). Returns seconds."""
    key = api_key() if key is None else key
    model = model or os.environ.get("TTS_MODEL") or MODEL                 # the production run may switch to an approved backup voice model
    if not key:
        raise TTSError("GEMINI_API_KEY is not set (environment or ~/arthvan-social/.env)")
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    raw = cache / (hashlib.sha1(f"{model}|{voice}|{STYLE}{text}".encode()).hexdigest() + ".wav")
    if not raw.exists():
        tries = daily_waits = 0
        while True:
            if model != MODEL and extra_spend() >= extra_cap():          # the approved amount for the extra voice models is used up (or not approved)
                raise TTSError("DAILY_VOICE_QUOTA: the approved budget for the extra voice models is used up")
            status, body = _generate(model, STYLE + text, voice, key)
            if status == 200:
                if model != MODEL:
                    record_spend(model, body.get("usageMetadata") or {})
                break
            wait = daily_quota_wait(body) if status == 429 else None
            if wait is not None and os.environ.get("TTS_NO_WAIT") == "1":
                raise TTSError("DAILY_VOICE_QUOTA: today's Google voice allowance is used up")
            if wait is not None and wait <= MAX_DAILY_WAIT and daily_waits < 2:     # today's allowance is used up: sleep until it resets
                daily_waits += 1; _wait_for_reset(wait); continue
            tries += 1
            if tries < 6 and status in (429, 500, 503):        # a per-minute quota or a busy server: wait it out, politely
                time.sleep(8 if status != 429 else 20 + 15 * (tries - 1)); continue
            raise TTSError(f"Gemini TTS failed ({status}): {str((body.get('error') or {}).get('message') or body)[:200].replace(key, '<key>')}")
        part = body["candidates"][0]["content"]["parts"][0]["inlineData"]
        data = base64.b64decode(part["data"])
        if "wav" in part.get("mimeType", ""):
            raw.write_bytes(data)
        else:   # raw 16-bit mono PCM; rate from the mime type, default 24 kHz
            mt = part.get("mimeType", ""); rate = int(mt.split("rate=")[1].split(";")[0]) if "rate=" in mt else 24000
            with wave.open(str(raw), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(data)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", "44100", "-ac", "2", str(out_wav)], check=True)
    with wave.open(str(out_wav)) as w:
        return w.getnframes() / w.getframerate()
