"""YouTube Data API v3: upload a vertical video as a Short to a channel, using a stored refresh token."""
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()
MAX_TITLE = 100


class YouTubeError(Exception):
    pass


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "<token>") if token else text


def call(method: str, url: str, token: str, *, json_body=None, data=None, headers=None):
    hdrs = {"Authorization": "Bearer " + token}
    hdrs.update(headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode(); hdrs["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=600, context=_CTX) as r:
            raw = r.read()
            return r.status, {k.lower(): v for k, v in r.headers.items()}, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raise YouTubeError(_scrub(f"HTTP {e.code}: {e.read().decode(errors='replace')[:400]}", token)) from None
    except Exception as e:
        raise YouTubeError(_scrub(f"{type(e).__name__}: {e}", token)) from None


def _post_form(url: str, form: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "error_description": e.read().decode(errors="replace")[:200]}


def access_token(client_id: str, client_secret: str, refresh_token: str, post=_post_form) -> str:
    out = post(TOKEN_URL, {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"})
    if "access_token" not in out:
        raise YouTubeError(f"token refresh failed: {out.get('error_description') or out.get('error')}")
    return out["access_token"]


def build_metadata(title: str, description: str, play_url: str, tags: list) -> dict:
    suffix = " #Shorts"
    t = title.strip()[: MAX_TITLE - len(suffix)].rstrip() + suffix
    return {"snippet": {"title": t, "description": f"{description.strip()}\n\nGet the app on Google Play: {play_url}",
                        "tags": [x.lstrip("#") for x in tags][:15], "categoryId": "22"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": True}}     # AI pictures and AI voice: YouTube's altered-content label, as sg-content does (23 Oct 2026)


def upload_short(token: str, path, metadata: dict) -> str:
    data = Path(path).read_bytes()
    status, headers, _ = call("POST", UPLOAD_URL, token, json_body=metadata,
                              headers={"X-Upload-Content-Length": str(len(data)), "X-Upload-Content-Type": "video/mp4"})
    if "location" not in headers:
        raise YouTubeError(f"resumable session not created ({status})")
    status, _, body = call("PUT", headers["location"], token, data=data, headers={"Content-Type": "video/mp4"})
    if status not in (200, 201) or "id" not in body:
        raise YouTubeError(f"upload returned {status} without a video id")
    return body["id"]


def post_short(channel: dict, path, title: str, description: str, play_url: str, tags: list) -> str:
    """channel: {client_id, client_secret, refresh_token}. Returns the YouTube video id."""
    tok = access_token(channel["client_id"], channel["client_secret"], channel["refresh_token"])
    return upload_short(tok, path, build_metadata(title, description, play_url, tags))
