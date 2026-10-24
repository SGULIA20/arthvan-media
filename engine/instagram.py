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


class PartialPublish(InstagramError):
    """Publishing stopped midway; `ids` holds what is already live."""

    def __init__(self, message: str, ids: dict):
        super().__init__(message)
        self.ids = ids


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
    reel_trial: bool = False         # the Reel went out as a Trial Reel (logged, so sg-content's 9 pm card can list it after 72 hours)


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


TRIAL = json.dumps({"graduation_strategy": "SS_PERFORMANCE"})


TRIAL_CONTAINERS: set = set()       # Reel containers this run made as Trial Reels


def reel_container(path: str, token: str, params: dict) -> str:
    """A Trial Reel first (non-followers see it first; Instagram shares the strong ones with followers; founder, 24 Oct 2026);
    a normal Reel shared to the feed when Instagram refuses the trial."""
    try:
        cid = call("POST", path, token, {**params, "trial_params": TRIAL})["id"]
        TRIAL_CONTAINERS.add(cid)
        return cid
    except InstagramError as e:
        print(f"trial reel refused ({str(e)[:100]}); posting a normal Reel", flush=True)
        return call("POST", path, token, {**params, "share_to_feed": "true"})["id"]


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
    reel = reel_container(path, token, {"media_type": "REELS", "video_url": urls.reel, "caption": captions.reel,
                                        "thumb_offset": str(thumb_offset_ms)})
    story = call("POST", path, token, {"media_type": "STORIES", "video_url": urls.story})["id"]
    for label, cid in (("post", post), ("reel", reel), ("story", story)):
        _wait(cid, token, label, sleep, max_polls, poll_s)
    return Prepared(post=post, reel=reel, story=story, reel_trial=reel in TRIAL_CONTAINERS)


def prepare_video_set(ig_id: str, token: str, video_url: str, caption: str, thumb_offset_ms: int = 2000,
                      sleep=time.sleep, max_polls: int = 90, poll_s: float = 4) -> Prepared:
    """A story ad: Reel + Story from one MP4, no carousel."""
    path = f"/{ig_id}/media"
    reel = reel_container(path, token, {"media_type": "REELS", "video_url": video_url, "caption": caption,
                                        "thumb_offset": str(thumb_offset_ms)})
    story = call("POST", path, token, {"media_type": "STORIES", "video_url": video_url})["id"]
    for label, cid in (("reel", reel), ("story", story)):
        _wait(cid, token, label, sleep, max_polls, poll_s)
    return Prepared(post=None, reel=reel, story=story, reel_trial=reel in TRIAL_CONTAINERS)


def publish_set(ig_id: str, token: str, prepared: Prepared) -> dict:
    ids = {}
    for label in ("post", "reel", "story"):
        if getattr(prepared, label) is None:
            continue
        try:
            out = call("POST", f"/{ig_id}/media_publish", token, {"creation_id": getattr(prepared, label)})
        except InstagramError as e:
            raise PartialPublish(f"publishing {label} failed after {sorted(ids)} were live: {e}", dict(ids)) from None
        ids[label] = out["id"]
    return ids


def refresh_token(token: str) -> dict:
    return call("GET", REFRESH_URL, token, {"grant_type": "ig_refresh_token", "access_token": token})
