"""A live status page for the founder: ~/Desktop/Arthvan-Reels/STATUS.html, rewritten every 30 seconds.
If the 'Updated' clock stops moving, this Mac (or the background job) has stopped; if the internet row turns red, the
connection is the problem.   python -m engine.status_page   (runs until stopped)"""
import html
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from . import broll, library, tts
from .config import ROOT

FOLDER = Path.home() / "Desktop" / "Arthvan-Reels"


def _sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def _reach(url: str) -> bool:
    """True when a TLS connection to the host in `url` works (directly, or through engine.netfix when the direct route is blocked)."""
    from urllib.parse import urlparse
    from .netfix import reachable
    return reachable(urlparse(url).hostname)


def _coverage_html() -> str:
    try:
        return library.coverage_html()
    except Exception as e:                       # the page must always render
        return f"<p>language table unavailable: {html.escape(str(e))}</p>"


def snapshot() -> dict:
    jobs = []
    for line in _sh("ps -eo etime=,args= | grep -E 'engine\\.(story|broll_library|poses)|refix\\.sh|capture_' | grep -v grep").splitlines():
        et, _, rest = line.strip().partition(" ")
        what = next((w for w in rest.split() if w.endswith(".json")), "") or ("re-render of fixed Reels" if "refix" in rest else rest[:60])
        jobs.append((et, what.replace("stories/", "")))
    voice_wait = None
    try:
        note = json.loads(tts.WAIT_NOTE.read_text())
        if note["until"] > time.time():
            voice_wait = datetime.fromtimestamp(note["until"]).strftime("%H:%M")
    except (OSError, ValueError, KeyError):
        pass
    reels = sorted(FOLDER.rglob("[0-9]*.mp4"))
    newest = max(reels, key=lambda p: p.stat().st_mtime) if reels else None
    return {"now": datetime.now().strftime("%d %b %H:%M:%S"), "jobs": jobs, "voice_wait": voice_wait, "languages": _coverage_html(), "reels": len(reels),
            "newest": (newest.name, datetime.fromtimestamp(newest.stat().st_mtime).strftime("%H:%M")) if newest else None,
            "credit": broll.status_line(), "net": {"Google": _reach("https://www.google.com/generate_204"),
                                                    "GitHub": _reach("https://api.github.com"), "Veo (Vertex AI)": _reach("https://us-central1-aiplatform.googleapis.com")}}


def render(s: dict) -> str:
    ok = lambda b: '<b style="color:#1a8f4a">OK</b>' if b else '<b style="color:#d33">NOT REACHABLE</b>'
    rows = "".join(f"<tr><td>{html.escape(w)}</td><td>running for {html.escape(et)}</td></tr>" for et, w in s["jobs"]) or "<tr><td colspan=2>nothing running right now</td></tr>"
    net = "".join(f"<tr><td>{k}</td><td>{ok(v)}</td></tr>" for k, v in s["net"].items())
    wait = (f'<p style="background:#fff3cd;padding:10px;border-radius:6px"><b>Waiting:</b> Google\'s free voice allowance for today is used up. '
            f'Work carries on by itself at about {s["voice_wait"]}.</p>') if s.get("voice_wait") else ""
    newest = f"{html.escape(s['newest'][0])} at {s['newest'][1]}" if s["newest"] else "none yet"
    return f"""<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=30><title>Reels status</title>
<body style="font:16px -apple-system,Helvetica,sans-serif;max-width:640px;margin:24px auto;padding:0 16px;color:#222">
<h2>Arthvan Reels: live status</h2>
<p style="font-size:22px"><b>Updated {s['now']}</b><br><span style="font-size:14px;color:#666">This clock moves every 30 seconds. If it stops, the Mac or the job has stopped. Reload the page to see the latest.</span></p>
{wait}<h3>Working on now</h3><table cellpadding=6>{rows}</table>
<h3>Finished</h3><p>{s['reels']} Reels in this folder. Newest: {newest}.</p>
<h3>Languages: how many Reels each language has, against English</h3>{s.get('languages', '')}
<h3>Google credit</h3><p>{html.escape(s['credit'])}</p>
<h3>Internet</h3><table cellpadding=6>{net}</table></body>"""


def main() -> int:
    FOLDER.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            (FOLDER / "STATUS.html").write_text(render(snapshot()))
        except Exception as e:
            (FOLDER / "STATUS.html").write_text(f"<meta http-equiv=refresh content=30><p>status page error: {html.escape(str(e))}")
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
