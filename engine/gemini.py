"""One small door to Gemini text generation. Key: GEMINI_API_KEY (environment or ~/arthvan-social/.env)."""
import json
import os
import ssl
import urllib.error
import urllib.request

from .tts import api_key

MODEL = "gemini-flash-lite-latest"
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class GeminiError(Exception):
    pass


def ask(prompt: str, *, model: str = MODEL, key: str = None, max_tokens: int = 1200) -> str:
    key = api_key() if key is None else key
    if not key:
        raise GeminiError("GEMINI_API_KEY is not set")
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.8}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        raise GeminiError(f"Gemini {model} failed ({e.code}): {e.read()[:200].decode(errors='replace').replace(key, '<key>')}")
    try:
        return "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"]).strip()
    except (KeyError, IndexError):
        raise GeminiError(f"Gemini {model}: empty answer")
