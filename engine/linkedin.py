"""LinkedIn Posts API: publish a multi-image post to the founder's personal profile (scope w_member_social)."""
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.linkedin.com"
VERSION = os.environ.get("LINKEDIN_VERSION", "202609")  # YYYYMM, must be a supported marketing version
MAX_COMMENTARY = 3000
_CAFILE = "/etc/ssl/cert.pem"  # this Mac's python.org build ships without root certificates
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()
_RESERVED = re.compile(r"([|{}@\[\]()<>#\\*_~])")


class LinkedInError(Exception):
    pass


def escape_little(text: str) -> str:
    """Reserved characters in post text must be backslash-escaped or LinkedIn may cut the post short."""
    return _RESERVED.sub(r"\\\1", text)


def commentary(text: str, tags: list) -> str:
    out = escape_little(text)
    if tags:
        out += "\n\n" + " ".join("{hashtag|\\#|%s}" % t.lstrip("#") for t in tags)
    if len(out) > MAX_COMMENTARY:
        raise LinkedInError(f"post text is {len(out)} characters, the limit is {MAX_COMMENTARY}")
    return out


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "<token>") if token else text


def call(method: str, url: str, token: str, *, json_body=None, data=None, headers=None):
    """Returns (status, response headers in lower case, parsed JSON body or {})."""
    hdrs = {"Authorization": "Bearer " + token, "Linkedin-Version": VERSION, "X-Restli-Protocol-Version": "2.0.0"}
    hdrs.update(headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
            raw = r.read()
            return r.status, {k.lower(): v for k, v in r.headers.items()}, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raise LinkedInError(_scrub(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}", token)) from None
    except Exception as e:
        raise LinkedInError(_scrub(f"{type(e).__name__}: {e}", token)) from None


def userinfo(token: str) -> dict:
    return call("GET", f"{API}/v2/userinfo", token)[2]


def upload_image(token: str, owner_urn: str, path) -> str:
    _, _, body = call("POST", f"{API}/rest/images?action=initializeUpload", token,
                      json_body={"initializeUploadRequest": {"owner": owner_urn}})
    value = body["value"]
    status, _, _ = call("PUT", value["uploadUrl"], token, data=Path(path).read_bytes(),
                        headers={"Content-Type": "application/octet-stream"})
    if status not in (200, 201):
        raise LinkedInError(f"image upload returned {status}")
    return value["image"]


def create_multi_image_post(token: str, author_urn: str, text: str, image_urns: list, alts: list) -> str:
    if not 2 <= len(image_urns) <= 20:
        raise LinkedInError("a multi-image post needs 2 to 20 images")
    body = {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
        "content": {"multiImage": {"images": [{"id": i, "altText": a} for i, a in zip(image_urns, alts)]}},
    }
    status, headers, _ = call("POST", f"{API}/rest/posts", token, json_body=body)
    if status != 201 or "x-restli-id" not in headers:
        raise LinkedInError(f"post creation returned {status} without an id")
    return headers["x-restli-id"]


def post_set(token: str, person_urn: str, text: str, tags: list, slide_paths: list, alts: list) -> str:
    """Upload the slides, then publish them as one swipeable post. Returns the post URN."""
    body = commentary(text, tags)
    urns = [upload_image(token, person_urn, p) for p in slide_paths]
    return create_multi_image_post(token, person_urn, body, urns, alts)
