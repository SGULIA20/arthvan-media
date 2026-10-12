"""Send the day's video to the founder's own WhatsApp (Gupshup partner API, approved template with a video header),
so he can post it as a status in two taps. Mirrors netlify/functions/lib/whatsapp.js in the ScoreMyBiz repo."""
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

PARTNER_BASE = "https://partner.gupshup.io/partner"
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class WhatsAppError(Exception):
    pass


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


def _app_token(cfg: dict) -> str:
    status, body = call("POST", f"{PARTNER_BASE}/account/login", form={"email": cfg["email"], "secret": cfg["secret"]})
    if status != 200 or not body.get("token"):
        raise WhatsAppError(f"Gupshup login failed ({status})")
    status, body = call("GET", f"{PARTNER_BASE}/app/{cfg['app_id']}/token", headers={"Authorization": body["token"], "token": body["token"]})
    tok = body.get("token"); tok = tok.get("token") if isinstance(tok, dict) else tok
    if status != 200 or not isinstance(tok, str):
        raise WhatsAppError(f"Gupshup app token failed ({status})")
    return tok


def send_status_video(cfg: dict, video_url: str, app_name: str, caption: str) -> str:
    to = re.sub(r"\D", "", cfg["to"])
    msg = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "template",
           "template": {"name": cfg["template"], "language": {"code": cfg.get("language", "en")}, "components": [
               {"type": "header", "parameters": [{"type": "video", "video": {"link": video_url}}]},
               {"type": "body", "parameters": [{"type": "text", "text": app_name}, {"type": "text", "text": caption[:900]}]}]}}
    for attempt in range(2):
        tok = _app_token(cfg)
        status, body = call("POST", f"{PARTNER_BASE}/app/{cfg['app_id']}/v3/message", json_body=msg, headers={"Authorization": tok})
        if status == 200:
            msgs = body.get("messages") or [{}]
            return msgs[0].get("id", "sent")
        if status == 401 and attempt == 0:
            continue
        text = str(body.get("message") or body)[:300].replace(cfg["secret"], "<secret>").replace(tok, "<token>")
        raise WhatsAppError(f"WhatsApp send failed ({status}): {text}")
    raise WhatsAppError("WhatsApp rejected the app token twice")
