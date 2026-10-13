"""Commands the founder sends to the Telegram bot: /status, /pause, /resume, /help.
A GitHub workflow runs this every few minutes (there is no always-on server), so an answer can take 5-10 minutes.
Only the founder's own chat is obeyed; anyone else who finds the bot is ignored. /pause writes the PAUSE file that run_daily
already honours and pushes it; /resume removes it."""
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import notify, telegram

ROOT = Path(__file__).resolve().parent.parent
MAX_AGE_SECONDS = 12 * 3600

HELP = ("I can do these:\n/status – what went out today, what is paused, what is next\n/pause – stop all posting until you say /resume\n"
        "/resume – start posting again\n/help – this list\n\nAnswers can take 5–10 minutes: I check for commands every few minutes.")


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
                  "Next: " + " | ".join(notify.upcoming(root, day - timedelta(days=1)))]
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
    return HELP


def poll(cfg: dict, root: Path = ROOT, *, call=telegram._call, send=telegram.send_message, change=git_change, day: date = None, now: float = None) -> int:
    """Answer every waiting command from the founder's chat, confirming each one so it is answered once. Returns how many."""
    day = day or lagos_today()
    now = time.time() if now is None else now
    updates = call(cfg["token"], "getUpdates", {"timeout": 0, "allowed_updates": ["message"]}).get("result", [])
    handled = 0
    for u in updates:
        m = u.get("message") or {}
        if str((m.get("chat") or {}).get("id")) == str(cfg["chat_id"]) and (m.get("text") or "").strip():
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
    print(f"answered {poll(cfg)} command(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
