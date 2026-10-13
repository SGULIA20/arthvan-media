"""Telegram Bot API: send the day's Reel to the founder's own Telegram chat, so he can forward it to his WhatsApp Status
in two taps. No 24-hour window, no template categories, nothing is silently dropped: a bad token or chat id is an error.
Setup (once): create a bot with @BotFather, put its token in TELEGRAM_BOT_TOKEN, message the bot, put the chat id in TELEGRAM_CHAT_ID."""
import json
import os
import ssl
import time
import urllib.error
import urllib.request

API = "https://api.telegram.org"
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class TelegramError(Exception):
    pass


def _call(token: str, method: str, body: dict, tries: int = 3):
    req = urllib.request.Request(f"{API}/bot{token}/{method}", data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    last = ""
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                time.sleep(5 * (attempt + 1)); continue
            raise TelegramError(f"Telegram {method} failed ({e.code}): {last.replace(token, '<token>')}") from None
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < tries - 1:
                time.sleep(5 * (attempt + 1)); continue
    raise TelegramError(f"Telegram {method} kept failing: {last.replace(token, '<token>')[:200]}")


def send_video(cfg: dict, video_url: str, caption: str) -> str:
    """cfg = {"token", "chat_id"}. Telegram fetches the public URL itself (up to 20 MB); returns the message id."""
    body = {"chat_id": cfg["chat_id"], "video": video_url, "caption": caption[:1000], "supports_streaming": True}
    res = _call(cfg["token"], "sendVideo", body)
    if not res.get("ok"):
        raise TelegramError(f"Telegram refused the video: {str(res)[:200].replace(cfg['token'], '<token>')}")
    return str(res["result"]["message_id"])


def find_chat_id(token: str) -> str:
    """After the founder has sent the bot any message: the chat id of the latest conversation."""
    res = _call(token, "getUpdates", {})
    chats = [u["message"]["chat"]["id"] for u in res.get("result", []) if "message" in u]
    if not chats:
        raise TelegramError("no messages yet: send the bot any message (for example /start) and try again")
    return str(chats[-1])
