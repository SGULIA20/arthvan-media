"""LinkedIn Posts API: publish a multi-image post to the founder's personal profile (scope w_member_social)."""
import json
import os
import re
import ssl
import time
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


def _post_body(author_urn: str, text: str, content: dict) -> dict:
    return {
        "author": author_urn, "commentary": text, "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
        "content": content,
    }


def _create_post(token: str, body: dict, what: str) -> str:
    status, headers, _ = call("POST", f"{API}/rest/posts", token, json_body=body)
    if status != 201 or "x-restli-id" not in headers:
        raise LinkedInError(f"{what} creation returned {status} without an id")
    return headers["x-restli-id"]


def create_multi_image_post(token: str, author_urn: str, text: str, image_urns: list, alts: list) -> str:
    if not 2 <= len(image_urns) <= 20:
        raise LinkedInError("a multi-image post needs 2 to 20 images")
    alts = list(alts) + [""] * (len(image_urns) - len(alts))          # every uploaded picture stays in the post
    content = {"multiImage": {"images": [{"id": i, "altText": a} for i, a in zip(image_urns, alts)]}}
    return _create_post(token, _post_body(author_urn, text, content), "post")


def post_set(token: str, person_urn: str, text: str, tags: list, slide_paths: list, alts: list) -> str:
    """Upload the slides, then publish them as one swipeable post. Returns the post URN."""
    body = commentary(text, tags)
    urns = [upload_image(token, person_urn, p) for p in slide_paths]
    return create_multi_image_post(token, person_urn, body, urns, alts)


def create_single_image_post(token: str, author_urn: str, text: str, image_urn: str, alt: str) -> str:
    return _create_post(token, _post_body(author_urn, text, {"media": {"id": image_urn, "altText": alt}}), "image post")


def post_images(token: str, person_urn: str, text: str, tags: list, paths: list, alts: list) -> str:
    """One picture = a single-image post; two or more = a swipeable multi-image post. Returns the post URN."""
    if not paths:
        raise LinkedInError("a picture post needs at least one picture")
    body = commentary(text, tags)
    urns = [upload_image(token, person_urn, p) for p in paths]
    if len(urns) == 1:
        return create_single_image_post(token, person_urn, body, urns[0], alts[0] if alts else "")
    return create_multi_image_post(token, person_urn, body, urns, alts)


def upload_document(token: str, owner_urn: str, path) -> str:
    _, _, body = call("POST", f"{API}/rest/documents?action=initializeUpload", token,
                      json_body={"initializeUploadRequest": {"owner": owner_urn}})
    value = body["value"]
    status, _, _ = call("PUT", value["uploadUrl"], token, data=Path(path).read_bytes(),
                        headers={"Content-Type": "application/octet-stream"})
    if status not in (200, 201):
        raise LinkedInError(f"document upload returned {status}")
    return value["document"]


def post_document(token: str, person_urn: str, text: str, tags: list, pdf_path, title: str) -> str:
    """A PDF as a swipeable document post (founder, 25 Oct 2026: tested against the single picture). Returns the post URN."""
    doc = upload_document(token, person_urn, pdf_path)
    return _create_post(token, _post_body(person_urn, commentary(text, tags), {"media": {"title": title[:200], "id": doc}}), "document post")


def jpegs_to_pdf(jpegs: list, out_path) -> Path:
    """One page per JPEG at its own pixel size, no extra packages (the JPEG goes in as-is)."""
    import struct
    objs, pages = [], []
    def size(data: bytes):
        i = 2
        while i < len(data):
            marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + length
        raise LinkedInError("not a JPEG")
    n = 2 + 3 * len(jpegs)                                   # catalog, pages, then image + content + page per JPEG
    kids = []
    for k, jp in enumerate(jpegs):
        data = Path(jp).read_bytes()
        w, h = size(data)
        img, cnt, pg = 3 + 3 * k, 4 + 3 * k, 5 + 3 * k
        objs.append((img, b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                          b"/Filter /DCTDecode /Length %d >>\nstream\n" % (w, h, len(data)) + data + b"\nendstream"))
        draw = b"q %d 0 0 %d 0 0 cm /Im0 Do Q" % (w, h)
        objs.append((cnt, b"<< /Length %d >>\nstream\n" % len(draw) + draw + b"\nendstream"))
        objs.append((pg, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /XObject << /Im0 %d 0 R >> >> "
                         b"/Contents %d 0 R >>" % (w, h, img, cnt)))
        kids.append(b"%d 0 R" % pg)
    objs = [(1, b"<< /Type /Catalog /Pages 2 0 R >>"), (2, b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count %d >>" % len(jpegs))] + objs
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num, body in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (n + 1)
    for num in range(1, n + 1):
        out += b"%010d 00000 n \n" % offsets[num]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (n + 1, xref)
    Path(out_path).write_bytes(bytes(out))
    return Path(out_path)


PART = 4194304  # LinkedIn splits uploads into 4 MiB parts


def upload_video(token: str, owner_urn: str, path, sleep=time.sleep, max_polls: int = 60) -> str:
    """Multipart video upload (3 s to 30 min, MP4, under 500 MB). Returns the video URN once AVAILABLE."""
    data = Path(path).read_bytes()
    _, _, body = call("POST", f"{API}/rest/videos?action=initializeUpload", token,
                      json_body={"initializeUploadRequest": {"owner": owner_urn, "fileSizeBytes": len(data),
                                                             "uploadCaptions": False, "uploadThumbnail": False}})
    v = body["value"]
    etags = []
    for part in v["uploadInstructions"]:
        chunk = data[part["firstByte"]: part["lastByte"] + 1]
        status, headers, _ = call("PUT", part["uploadUrl"], token, data=chunk, headers={"Content-Type": "application/octet-stream"})
        if status not in (200, 201) or "etag" not in headers:
            raise LinkedInError(f"video part upload returned {status} without an etag")
        etags.append(headers["etag"])
    call("POST", f"{API}/rest/videos?action=finalizeUpload", token,
         json_body={"finalizeUploadRequest": {"video": v["video"], "uploadToken": v.get("uploadToken", ""), "uploadedPartIds": etags}})
    for _ in range(max_polls):
        _, _, info = call("GET", f"{API}/rest/videos/{urllib.parse.quote(v['video'], safe='')}", token)
        if info.get("status") == "AVAILABLE":
            return v["video"]
        if info.get("status") == "PROCESSING_FAILED":
            raise LinkedInError(f"video processing failed: {info.get('processingFailureReason')}")
        sleep(5)
    raise LinkedInError("video never became available")


def create_video_post(token: str, author_urn: str, text: str, video_urn: str, title: str) -> str:
    return _create_post(token, _post_body(author_urn, text, {"media": {"id": video_urn, "title": title}}), "video post")


def post_video(token: str, person_urn: str, text: str, tags: list, video_path, title: str) -> str:
    body = commentary(text, tags)
    return create_video_post(token, person_urn, body, upload_video(token, person_urn, video_path), title)
