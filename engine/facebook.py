"""Facebook Page Reels and Stories through the Graph API (Meta's Video API). Both use the same three steps:
start (get a video id and an upload address) -> upload the file straight from this machine -> finish (publish).
Needs a Facebook PAGE (not a personal profile) and a Page access token with pages_manage_posts, pages_read_engagement and pages_show_list.
Reels: 9:16, 3-90 s. Stories: 9:16, up to 60 s. Env: FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN."""
import json
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH = "https://graph.facebook.com/v25.0"
STORY_MAX_SECONDS = 60.0
REEL_MAX_SECONDS = 90.0
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if Path(_CAFILE).exists() else ssl.create_default_context()


class FacebookError(Exception):
    pass


def _scrub(cfg: dict, text: str) -> str:
    return str(text).replace(cfg["token"], "<token>")


def _request(cfg: dict, method: str, url: str, *, form: dict = None, headers: dict = None, body: bytes = None, tries: int = 3):
    data = body if body is not None else (urllib.parse.urlencode({**(form or {}), "access_token": cfg["token"]}).encode() if form is not None else None)
    last = ""
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=300, context=_CTX) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            last = e.read().decode(errors="replace")[:400]
            if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                time.sleep(5 * (attempt + 1)); continue
            raise FacebookError(f"Facebook {method} {urllib.parse.urlparse(url).path} failed ({e.code}): {_scrub(cfg, last)}") from None
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < tries - 1:
                time.sleep(5 * (attempt + 1)); continue
    raise FacebookError(f"Facebook {method} {urllib.parse.urlparse(url).path} kept failing: {_scrub(cfg, last)[:200]}")


def duration_seconds(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise FacebookError(f"could not read the length of {Path(path).name}") from None


def _publish(cfg: dict, edge: str, path, extra: dict, *, wait: float = 6.0, polls: int = 20) -> str:
    path = Path(path)
    started = _request(cfg, "POST", f"{GRAPH}/{cfg['page_id']}/{edge}", form={"upload_phase": "start"})
    video_id, upload_url = started.get("video_id"), started.get("upload_url")
    if not (video_id and upload_url):
        raise FacebookError(f"Facebook did not start the upload: {_scrub(cfg, json.dumps(started))[:200]}")
    size = path.stat().st_size
    sent = _request(cfg, "POST", upload_url, body=path.read_bytes(),
                    headers={"Authorization": f"OAuth {cfg['token']}", "offset": "0", "file_size": str(size), "Content-Type": "application/octet-stream"})
    if not sent.get("success"):
        raise FacebookError(f"Facebook did not accept the video: {_scrub(cfg, json.dumps(sent))[:200]}")
    for _ in range(polls):                                           # wait until the upload is complete (processing continues after publishing)
        st = (_request(cfg, "GET", f"{GRAPH}/{video_id}?" + urllib.parse.urlencode({"fields": "status", "access_token": cfg["token"]})).get("status") or {})
        up = (st.get("uploading_phase") or {}).get("status")
        if st.get("video_status") == "error" or up == "error":
            raise FacebookError(f"Facebook rejected the video while uploading: {_scrub(cfg, json.dumps(st))[:200]}")
        if up in (None, "complete") or st.get("video_status") == "ready":
            break
        time.sleep(wait)
    done = _request(cfg, "POST", f"{GRAPH}/{cfg['page_id']}/{edge}", form={"upload_phase": "finish", "video_id": video_id, **extra})
    if done.get("success") is False:
        raise FacebookError(f"Facebook did not publish: {_scrub(cfg, json.dumps(done))[:200]}")
    return str(done.get("post_id") or video_id)


def post_reel(cfg: dict, path, description: str) -> str:
    """cfg = {"page_id", "token"}. Publishes the video as a Facebook Reel; returns the post id."""
    secs = duration_seconds(path)
    if secs > REEL_MAX_SECONDS:
        raise FacebookError(f"the video is {secs:.0f} s; Facebook Reels allow up to {REEL_MAX_SECONDS:.0f} s")
    return _publish(cfg, "video_reels", path, {"video_state": "PUBLISHED", "description": description[:2000]})


def post_story(cfg: dict, path) -> str:
    """Publishes the video as a Facebook Page Story (up to 60 s); returns the post id."""
    secs = duration_seconds(path)
    if secs > STORY_MAX_SECONDS:
        raise FacebookError(f"the video is {secs:.0f} s; Facebook Stories allow up to {STORY_MAX_SECONDS:.0f} s")
    return _publish(cfg, "video_stories", path, {})
