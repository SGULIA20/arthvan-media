"""Instagram API with Instagram Login (graph.instagram.com). Prepare everything, then publish."""
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API = "https://graph.instagram.com/v25.0"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
_CAFILE = "/etc/ssl/cert.pem"  # this Mac's python.org build ships without root certificates
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class InstagramError(Exception):
    pass


@dataclass(frozen=True)
class SetUrls:
    slides: list
    reel: str
    story: str


@dataclass(frozen=True)
class Captions:
    post: str
    reel: str


@dataclass(frozen=True)
class Prepared:
    post: str
    reel: str
    story: str


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
        raise InstagramError(_scrub(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}", token)) from None
    except Exception as e:  # network trouble, bad JSON
        raise InstagramError(_scrub(f"{type(e).__name__}: {e}", token)) from None


def _wait(cid: str, token: str, label: str, sleep, max_polls: int, poll_s: float) -> None:
    for _ in range(max_polls):
        status = call("GET", f"/{cid}", token, {"fields": "status_code"}).get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise InstagramError(f"{label} container failed with status {status}")
        sleep(poll_s)
    raise InstagramError(f"{label} container never finished")


def prepare_set(ig_id: str, token: str, urls: SetUrls, captions: Captions, thumb_offset_ms: int = 2000,
                sleep=time.sleep, max_polls: int = 90, poll_s: float = 4) -> Prepared:
    """Create every container and wait until all are FINISHED. Nothing is public yet."""
    path = f"/{ig_id}/media"
    children = []
    for i, u in enumerate(urls.slides):
        cid = call("POST", path, token, {"image_url": u, "is_carousel_item": "true"})["id"]
        _wait(cid, token, f"slide {i + 1}", sleep, max_polls, poll_s)
        children.append(cid)
    post = call("POST", path, token, {"media_type": "CAROUSEL", "children": ",".join(children),
                                      "caption": captions.post})["id"]
    reel = call("POST", path, token, {"media_type": "REELS", "video_url": urls.reel, "caption": captions.reel,
                                      "share_to_feed": "true", "thumb_offset": str(thumb_offset_ms)})["id"]
    story = call("POST", path, token, {"media_type": "STORIES", "video_url": urls.story})["id"]
    for label, cid in (("post", post), ("reel", reel), ("story", story)):
        _wait(cid, token, label, sleep, max_polls, poll_s)
    return Prepared(post=post, reel=reel, story=story)


def publish_set(ig_id: str, token: str, prepared: Prepared) -> dict:
    ids = {}
    for label in ("post", "reel", "story"):
        out = call("POST", f"/{ig_id}/media_publish", token, {"creation_id": getattr(prepared, label)})
        ids[label] = out["id"]
    return ids


def refresh_token(token: str) -> dict:
    return call("GET", REFRESH_URL, token, {"grant_type": "ig_refresh_token", "access_token": token})
