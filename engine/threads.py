"""Threads API (graph.threads.net): publish the day's slides as one carousel with text."""
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://graph.threads.net/v1.0"
REFRESH_URL = "https://graph.threads.net/refresh_access_token"
MAX_TEXT = 500
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class ThreadsError(Exception):
    pass


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "<token>") if token else text


def call(method: str, path: str, token: str, params: dict = None) -> dict:
    url = path if path.startswith("http") else API + path
    data = None
    if method == "GET" and params:
        url += "?" + urllib.parse.urlencode(params)
    elif params:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ThreadsError(_scrub(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}", token)) from None
    except Exception as e:
        raise ThreadsError(_scrub(f"{type(e).__name__}: {e}", token)) from None


def _wait(cid: str, token: str, label: str, sleep, max_polls: int, poll_s: float) -> None:
    for _ in range(max_polls):
        s = call("GET", f"/{cid}", token, {"fields": "status,error_message"})
        if s.get("status") == "FINISHED":
            return
        if s.get("status") in ("ERROR", "EXPIRED"):
            raise ThreadsError(f"{label} container failed: {s.get('error_message') or s.get('status')}")
        sleep(poll_s)
    raise ThreadsError(f"{label} container never finished")


def post_carousel(uid: str, token: str, image_urls: list, text: str, sleep=time.sleep,
                  max_polls: int = 40, poll_s: float = 5) -> str:
    if len(text) > MAX_TEXT:
        raise ThreadsError(f"text is {len(text)} characters, Threads allows {MAX_TEXT}")
    if not 2 <= len(image_urls) <= 20:
        raise ThreadsError("a Threads carousel needs 2 to 20 images")
    children = []
    for i, u in enumerate(image_urls):
        cid = call("POST", f"/{uid}/threads", token, {"media_type": "IMAGE", "image_url": u, "is_carousel_item": "true"})["id"]
        _wait(cid, token, f"image {i + 1}", sleep, max_polls, poll_s)
        children.append(cid)
    cid = call("POST", f"/{uid}/threads", token, {"media_type": "CAROUSEL", "children": ",".join(children), "text": text})["id"]
    _wait(cid, token, "carousel", sleep, max_polls, poll_s)
    return call("POST", f"/{uid}/threads_publish", token, {"creation_id": cid})["id"]


def me(token: str) -> dict:
    return call("GET", "/me", token, {"fields": "id,username"})


def refresh_token(token: str) -> dict:
    return call("GET", REFRESH_URL, token, {"grant_type": "th_refresh_token", "access_token": token})
