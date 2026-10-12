"""Send the day's video to the founder's own WhatsApp (Gupshup self-serve API, approved template with a video header),
so he can post it as a status in two taps. Auth is the App API Key shown on the app's Settings tab at gupshup.ai;
the template is looked up by name among the APPROVED ones, so the GitHub variable stays a name, not an id."""
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.gupshup.io"
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class WhatsAppError(Exception):
    pass


class WhatsAppNotReady(WhatsAppError):
    """The template is still with Meta: nothing is wrong, try again next run."""


def call(method: str, url: str, *, form=None, json_body=None, headers=None):
    hdrs = dict(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode(); hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif json_body is not None:
        data = json.dumps(json_body).encode(); hdrs["Content-Type"] = "application/json"; hdrs["Accept"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"message": raw[:300]}


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _scrub(cfg: dict, text: str) -> str:
    return text.replace(cfg["api_key"], "<key>")


def _template_id(cfg: dict) -> str:
    """The id of the approved template called cfg['template'] in cfg['language'] (default en)."""
    lang = cfg.get("language", "en")
    url = f"{API_BASE}/wa/app/{cfg['app_id']}/template?templateStatus=APPROVED&pageSize=100"
    status, body = call("GET", url, headers={"apikey": cfg["api_key"]})
    if status != 200:
        raise WhatsAppError(_scrub(cfg, f"Gupshup template list failed ({status}): {str(body.get('message') or body)[:200]}"))
    for t in body.get("templates") or []:
        if t.get("elementName") == cfg["template"] and t.get("status") == "APPROVED" and t.get("languageCode", lang) == lang:
            return t["id"]
    raise WhatsAppNotReady(f"template {cfg['template']} ({lang}) is not approved yet on app {cfg['app_id']}")


def send_status_video(cfg: dict, video_url: str, app_name: str, caption: str) -> str:
    tid = _template_id(cfg)
    form = {"channel": "whatsapp", "source": _digits(cfg["source"]), "destination": _digits(cfg["to"]), "src.name": cfg["app_name"],
            "template": json.dumps({"id": tid, "params": [app_name, caption[:900]]}),
            "message": json.dumps({"type": "video", "video": {"link": video_url}})}
    last = ""
    for attempt in range(2):
        status, body = call("POST", f"{API_BASE}/wa/api/v1/template/msg", form=form, headers={"apikey": cfg["api_key"]})
        if status in (200, 202):
            return body.get("messageId") or "sent"
        last = _scrub(cfg, str(body.get("message") or body)[:300])
        if status == 401 or attempt == 1:
            break
    raise WhatsAppError(f"WhatsApp send failed ({status}): {last}")
