"""Commands the founder sends to the Telegram bot: /status, /pause, /resume, /comment, /help, and a Reel video for an X-ray (engine/xray.py).
A GitHub workflow runs this every few minutes (there is no always-on server), so an answer can take 5-10 minutes.
Only the founder's own chat is obeyed; anyone else who finds the bot is ignored. /pause writes the PAUSE file that run_daily
already honours and pushes it; /resume removes it."""
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import comment_drafts, notify, telegram, xray

ROOT = Path(__file__).resolve().parent.parent
MAX_AGE_SECONDS = 12 * 3600
# 4 Nov 2026 (founder, test C): a video captioned "intro <piece id>" is the founder's 10-second opening for that sg-content Short or long.
# It is saved under inbox/intro/ (not X-rayed) so Claude can splice it in front of the rendered piece.
INTRO_RE = re.compile(r"^\s*intro\s+(\d{4}-\d{2}-\d{2}-(?:sglearning|arthvan)-(?:short|long))\s*$", re.I)
INTRO_DIR = "inbox/intro"

HELP = ("I can do these:\n/status – what went out today, what is paused, what is next\n/pause – stop all posting until you say /resume\n"
        "/resume – start posting again\n/comment <post text> – two LinkedIn comment drafts in your voice\n"
        "🎬 Send any Reel's video (screen recording or saved Reel, under 20 MB), caption optional – a Reel X-ray: why it works, what to copy\n"
        "🎬 Send your 10-second intro with the caption intro <piece id> (e.g. intro 2026-11-07-sglearning-short) – saved for the splice\n"
        "/help – this list\n\nAnswers can take 5–10 minutes: I check for commands every few minutes.")


def git_change(root: Path, add: list, remove: list, message: str) -> None:
    def git(*a): subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
    git("config", "user.name", "arthvan-autoposter"); git("config", "user.email", "autoposter@users.noreply.github.com")
    for f in add: git("add", f)
    for f in remove: git("rm", "-q", "--ignore-unmatch", f)
    git("commit", "-m", message)
    git("pull", "--rebase", "origin", "main")
    git("push", "origin", "HEAD:main")


def lagos_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).date()


def status(root: Path, day: date) -> str:
    paused = (root / "PAUSE").exists()
    lines = ["⏸ Posting is PAUSED. Send /resume to start again." if paused else "▶️ Posting is on."]
    if notify.day_state(root / "logs" / "posts.jsonl", day):
        lines += ["", notify.daily_summary(root, day)]
    else:
        lines += ["", f"Nothing posted yet today ({day.day} {day.strftime('%b')}); the post goes out around 6 PM Lagos.", notify.buffer_line(root, day),
                  "Next: " + " | ".join(notify.upcoming(root, day - timedelta(days=1))), notify.personal_line(root, day)]
    return "\n".join(lines)


def answer(text: str, root: Path, day: date, change=git_change) -> str:
    cmd = text.split()[0].split("@")[0].lower() if text.strip() else ""
    flag = root / "PAUSE"
    if cmd == "/status":
        return status(root, day)
    if cmd == "/pause":
        if flag.exists():
            return "Already paused. Send /resume to start again."
        flag.write_text(f"paused from Telegram {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
        change(root, ["PAUSE"], [], "pause posting (from Telegram)")
        return "⏸ Paused. Nothing will be posted until you send /resume. (A run already under way may still finish.)"
    if cmd == "/resume":
        if not flag.exists():
            return "Posting is already on."
        flag.unlink()
        change(root, [], ["PAUSE"], "resume posting (from Telegram)")
        return "▶️ Posting is back on. The next run goes out at its usual time."
    if cmd == "/comment":
        return comment_drafts.drafts(text.strip()[len(text.split()[0]):])
    return HELP


def download(cfg: dict, file_id: str, out: Path, call=telegram._call) -> Path:
    import urllib.request
    path = call(cfg["token"], "getFile", {"file_id": file_id})["result"]["file_path"]
    with urllib.request.urlopen(f"{telegram.API}/file/bot{cfg['token']}/{path}", timeout=180, context=telegram._CTX) as r:
        out.write_bytes(r.read())
    return out


def intro_id(message: dict) -> str:
    m = INTRO_RE.match(message.get("caption") or "")
    return m.group(1).lower() if m else ""


def intro_reply(cfg: dict, message: dict, root: Path, *, call=telegram._call, change=git_change, fetch=download) -> str:
    """The founder's intro clip for one piece: saved as inbox/intro/<piece id>.mp4 and pushed, replacing any earlier clip for that piece."""
    v = xray.video_of(message)
    pid = intro_id(message)
    if (v.get("file_size") or 0) > xray.MAX_BYTES:
        return "🎬 That intro is over 20 MB, the most a bot can download. Send it again as a normal video (Telegram compresses it)."
    out = Path(root) / INTRO_DIR / f"{pid}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    fetch(cfg, v["file_id"], out, call)
    rel = str(out.relative_to(root))
    try:
        change(root, [rel], [], f"intro clip for {pid}")
    except Exception as e:
        return f"🎬 Intro for {pid} downloaded but could not be saved to git: {str(e)[:160]}. Send it again in a few minutes."
    secs = v.get("duration")
    return (f"🎬 Intro for {pid} saved ({out.stat().st_size / 1e6:.1f} MB{f', {secs} s' if secs else ''}). "
            f"Claude splices it in front of the piece; the preview comes back here.")


def xray_reply(cfg: dict, message: dict, root: Path, *, call=telegram._call, change=git_change, analyse=xray.analyse, fetch=download) -> str:
    """A Reel video from the founder: download it, let Gemini watch it, save the breakdown under logs/xray/ and answer with it."""
    import tempfile
    v = xray.video_of(message)
    note = (message.get("caption") or "").replace("/xray", "").strip()
    if (v.get("file_size") or 0) > xray.MAX_BYTES:
        return ("🎬 That video is over 20 MB, the most a bot can download. Send it again as a normal video (Telegram compresses it), "
                "or trim it to the first 60 seconds.")
    with tempfile.TemporaryDirectory() as tmp:
        path = fetch(cfg, v["file_id"], Path(tmp) / "reel.mp4", call)
        try:
            text = analyse(path, note)
        except Exception as e:
            return f"🎬 Reel X-ray failed: {str(e)[:200]}. Send the video again in a few minutes."
    saved = xray.save(root, note, text)
    try:
        change(root, [str(saved.relative_to(root))], [], "Reel X-ray from Telegram")
    except Exception as e:                                   # the answer still reaches the founder; the file waits for the next push
        print(f"could not save the X-ray to git: {e}")
    return "🎬 Reel X-ray\n\n" + text[:3900]


def poll(cfg: dict, root: Path = ROOT, *, call=telegram._call, send=telegram.send_message, change=git_change, day: date = None, now: float = None,
         xray_fn=xray_reply, intro_fn=intro_reply) -> int:
    """Answer every waiting command from the founder's chat, confirming each one so it is answered once. Returns how many."""
    day = day or lagos_today()
    now = time.time() if now is None else now
    updates = call(cfg["token"], "getUpdates", {"timeout": 0, "allowed_updates": ["message"]}).get("result", [])
    handled = 0
    for u in updates:
        m = u.get("message") or {}
        mine = str((m.get("chat") or {}).get("id")) == str(cfg["chat_id"])
        if mine and xray.video_of(m) and intro_id(m):
            call(cfg["token"], "getUpdates", {"offset": u["update_id"] + 1, "timeout": 0})     # saved once, even if this run dies
            send(cfg, intro_fn(cfg, m, root, call=call, change=change)); handled += 1
            continue
        if mine and xray.video_of(m):
            send(cfg, "🎬 Got the Reel. Watching it now, the X-ray comes in a minute or two."); handled += 1
            call(cfg["token"], "getUpdates", {"offset": u["update_id"] + 1, "timeout": 0})     # never watched twice, even if this run dies
            send(cfg, xray_fn(cfg, m, root, call=call, change=change))
            continue
        if mine and (m.get("text") or "").strip():
            if now - m.get("date", now) > MAX_AGE_SECONDS:
                reply = "That command is more than 12 hours old, so I ignored it. Send it again if you still want it."
            else:
                reply = answer(m["text"], root, day, change)
            send(cfg, reply); handled += 1
        call(cfg["token"], "getUpdates", {"offset": u["update_id"] + 1, "timeout": 0})
    return handled


def main() -> int:
    cfg = notify.config()
    if not cfg:
        print("Telegram is not set up (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return 1
    try:
        print(f"answered {poll(cfg)} command(s)")
    except telegram.TelegramError as e:
        if "(5" not in str(e):                      # a 5xx is Telegram's own outage (30 Oct 2026: 504 Gateway Timeout); the next run answers
            raise
        print(f"Telegram is down for the moment, commands wait for the next run: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
