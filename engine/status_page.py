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


def _job_name(rest: str) -> str:
    if "pretranslate" in rest:
        return "Writing the scripts in other languages"
    if "prefilm" in rest:
        return "Filming video shots"
    if "daily_production" in rest:
        return "Production run (makes the Reels one after another)"
    if "engine.story" in rest or "engine/story" in rest:
        name = next((w for w in rest.split() if w.endswith(".json")), "")
        return "Making the Reel " + Path(name).stem.replace("_", "-") if name else "Making a Reel"
    if "refix" in rest:
        return "Re-rendering fixed Reels"
    return rest[:60]


_QUEUE = {"at": 0.0, "value": None}


def _queue() -> dict:
    """How much work is still waiting (recomputed at most every 5 minutes: it reads every Reel's shot list)."""
    if time.time() - _QUEUE["at"] > 300 or _QUEUE["value"] is None:
        try:
            from . import daily_production as dp
            conv = len(dp.backlog())
            _QUEUE.update(at=time.time(), value={"conversions": conv, "english": len(dp.pending_english()), "days": max(1, round(conv / 12))})
        except Exception:
            _QUEUE.update(at=time.time(), value={"conversions": None, "english": None, "days": None})
    return _QUEUE["value"]


def _power() -> dict:
    out = _sh("pmset -g batt")
    pct = next((int(t.rstrip("%;")) for t in out.replace(";", " ").split() if t.endswith("%") or t.rstrip(";").endswith("%")), None)
    return {"on_battery": "Battery Power" in out, "percent": pct}


def _voice_today() -> dict:
    """Google's free voice allowance (100 lines a day) runs on the US Pacific day: it resets at 08:00 WAT (09:00 after the US clocks change)."""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    pt = datetime.now(timezone.utc).astimezone(ZoneInfo("America/Los_Angeles"))
    start = pt.replace(hour=0, minute=0, second=0, microsecond=0)
    cache = ROOT / "stories" / "cache"
    used = sum(1 for f in cache.glob("*.wav") if f.stat().st_mtime >= start.timestamp()) if cache.exists() else 0
    nxt = (start + __import__("datetime").timedelta(days=1)).astimezone(ZoneInfo("Africa/Lagos"))
    return {"used": used, "limit": 100, "resets": nxt.strftime("%H:%M")}


def _languages_html() -> str:
    """Every language each app supports: how many scripts are written and how many Reels are made, against the English Reels."""
    try:
        cov = library.coverage(targets=library.TARGETS_BY_APP)
    except Exception as e:
        return f"<p>language table unavailable: {html.escape(str(e))}</p>"

    def bar(n, total, colour):
        pct = 0 if not total else round(100 * n / total)
        return (f"<div style='display:flex;align-items:center;gap:8px'><div style='flex:1;background:#e8e8ee;border-radius:4px;height:10px;min-width:70px'>"
                f"<div style='width:{pct}%;background:{colour};height:10px;border-radius:4px'></div></div><span style='min-width:58px;text-align:right'>{n} / {total}</span></div>")
    out = []
    for app, c in cov.items():
        eng, rows = c["english"], c["rows"]
        scripts = sum(r["made"] + r["scripted"] for r in rows if r["lang"] in library.TARGETS_BY_APP.get(app, []))
        made = sum(r["made"] for r in rows if r["lang"] in library.TARGETS_BY_APP.get(app, []))
        total = eng * len(library.TARGETS_BY_APP.get(app, []))
        body = ""
        for r in rows:
            if r["lang"] not in library.TARGETS_BY_APP.get(app, []):
                continue
            written = r["made"] + r["scripted"]
            state = ("<b style='color:#1a8f4a'>all made</b>" if r["made"] >= eng else
                     "<span style='color:#b8860b'>video queue</span>" if written >= eng else
                     "<span style='color:#d33'>writing scripts</span>" if written else "<span style='color:#999'>not started</span>")
            body += (f"<tr><td><b>{r['name']}</b></td><td>{bar(written, eng, '#d99a00')}</td><td>{bar(r['made'], eng, '#1a8f4a')}</td><td>{state}</td></tr>")
        out.append(f"<h3>{library.APPS.get(app, app)}: {eng} English Reels ({c['english_made']} made)</h3>"
                   f"<p style='margin:4px 0;color:#555'>Scripts written in other languages: <b>{scripts}</b> of {total} &nbsp;|&nbsp; Language Reels made: <b>{made}</b> of {total}</p>"
                   f"<div style='overflow-x:auto'><table cellpadding=5 style='width:100%;min-width:480px;border-collapse:collapse'><tr style='text-align:left;color:#666;font-size:13px'><th>Language</th><th>Scripts written</th><th>Reels made</th><th>State</th></tr>{body}</table></div>")
    return "".join(out)


def snapshot() -> dict:
    jobs = []
    for line in _sh("ps -eo etime=,args= | grep -E 'engine\\.(story|broll_library|poses|daily_production)|pretranslate|prefilm|refix\\.sh|capture_' | grep -v grep").splitlines():
        et, _, rest = line.strip().partition(" ")
        name = _job_name(rest)
        if not any(n == name for _e, n in jobs):                 # the caffeinate wrapper and the program itself are one job
            jobs.append((et, name))
    voice_wait = None
    try:
        note = json.loads(tts.WAIT_NOTE.read_text())
        if note["until"] > time.time():
            voice_wait = datetime.fromtimestamp(note["until"]).strftime("%H:%M")
    except (OSError, ValueError, KeyError):
        pass
    reels = sorted(FOLDER.rglob("[0-9]*.mp4"))
    newest = max(reels, key=lambda p: p.stat().st_mtime) if reels else None
    return {"now": datetime.now().strftime("%d %b %H:%M:%S"), "jobs": jobs, "voice_wait": voice_wait, "languages": _languages_html(), "queue": _queue(), "power": _power(), "voice": _voice_today(), "extra_voice": {"spent": tts.extra_spend(), "cap": tts.extra_cap()}, "reels": len(reels),
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
    pw = s.get("power") or {}
    power_html = ((f'<p style="background:#ffe3e3;padding:10px;border-radius:6px"><b>Mac is on battery ({pw.get("percent")}%).</b> It sleeps on battery and Reel work slows down or stops. '
                   f'Plug in the charger and keep the lid open.</p>') if pw.get("on_battery") else
                  f'<p style="background:#e6f6ec;padding:10px;border-radius:6px">Mac is plugged in ({pw.get("percent")}%).</p>') if pw else ""
    q = s.get("queue") or {}
    queue_html = (f'<p style="background:#f4f4f6;padding:10px;border-radius:6px"><b>Still to do:</b> {q["conversions"]} language Reels to make from the finished English ones '
                  f'(about {q["days"]} days at 12 a day), and {q["english"]} English Reels still to render. '
                  f'Order now: conversions first, then English Reels already filmed, then cut-out English.</p>') if q.get("conversions") is not None else ""
    ev = s.get("extra_voice") or {}
    extra_html = (f'<p style="background:#fff8e1;padding:10px;border-radius:6px"><b>Extra voice budget:</b> about ₹{ev["spent"]:.0f} of ₹{ev["cap"]:.0f} used '
                  f'(counted cautiously, so the real bill is probably lower). When it reaches the limit the extra voices switch off by themselves.</p>') if ev.get("cap") else ""
    v = s.get("voice") or {}
    voice_html = (f'<p style="background:#eef2ff;padding:10px;border-radius:6px"><b>Voice allowance today:</b> {v["used"]} of about {v["limit"]} lines used. '
                  f'Resets at {v["resets"]} (Lagos time). About 7 lines make one Reel.</p>') if v else ""
    return f"""<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=30><title>Reels status</title>
<body style="font:16px -apple-system,Helvetica,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#222">
<h2>Arthvan Reels: live status</h2>
<p style="font-size:22px"><b>Updated {s['now']}</b><br><span style="font-size:14px;color:#666">This clock moves every 30 seconds. If it stops, the Mac or the job has stopped. Reload the page to see the latest.</span></p>
{wait}{power_html}{voice_html}{extra_html}{queue_html}<h3>Working on now</h3><table cellpadding=6>{rows}</table>
<h3>Finished</h3><p>{s['reels']} Reels in this folder. Newest: {newest}.</p>
<h3>All languages: scripts written and Reels made</h3><p style="color:#666;font-size:14px;margin:2px 0">Scripts written = the translated script exists. Reels made = the finished video in that language. Gold bar = scripts, green bar = finished Reels.</p>{s.get('languages', '')}
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
