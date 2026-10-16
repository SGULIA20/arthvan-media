"""The daily production run, started by a Mac launch agent at 08:30 and again at 09:30 WAT (Google's free voice allowance resets at US Pacific midnight: 08:00 WAT, 09:00 after the US clocks change on 1 Nov) with nobody watching:

  1. English originals that are scripted but not made yet: made with the free Google video credit while it lasts (ledger guard, 10 Dec),
     then in the free in-house cut-out style.
  2. Then conversions: every finished English Reel into the languages each app supports, in a fixed priority (Hindi first, then the other
     Indian languages, then the international ones). Only Reels whose video shots are already paid for are converted: a conversion never
     spends video credit. Translations are written by Gemini (engine/translator.py, draft quality) unless a hand-written file exists.
  3. Stops when the day's voice budget (~100 lines) is used, files everything into App/Language folders, and sends a Telegram summary.
python -m engine.daily_production --dry     show today's plan, make nothing"""
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import broll, calendar_plan, library, localize, notify, translator, tts
from .config import load_apps

ROOT = Path(__file__).resolve().parent.parent
LOG = Path.home() / "arthvan-social" / "logs" / "production.jsonl"
LOCK = Path.home() / "arthvan-social" / "logs" / "production.lock"
PRIORITY = ["hi", "gu", "mr", "ta", "bn", "te", "kn", "ml", "ur", "es", "pt", "sw", "ar", "de", "fr", "it", "nl", "fi", "id"]
# each app's languages that our apps support AND whose Google voice was checked (pa, or, as, yo, ha, ig are not speakable yet)
SUPPORTED = {"scoremybiz": {"hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "ur", "ar", "sw", "de", "fr", "es", "it", "pt", "nl", "fi"},
             "waypoint": {"hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "es", "fr", "de", "pt", "id", "sw"}}
MAX_TRIES = 3
MAX_SECONDS = 59.8
VOICE_BUDGET = 92


NETWORK_WORDS = ("nodename nor servname", "Temporary failure in name resolution", "Network is unreachable", "URLError", "Connection reset",
                 "Connection refused", "ConnectionError", "timed out", "Name or service not known", "IncompleteRead", "RemoteDisconnected", "connection interrupted")


INTERRUPTED_WORDS = ("TimeoutError", "Timeout 30000ms exceeded", "Timeout exceeded", "Target closed", "has been closed", "Browser closed", "Call log:")


def is_interrupted(text: str) -> bool:
    """A Playwright timeout is measured on the wall clock, so a Mac that sleeps mid-render makes it expire: not the Reel's fault."""
    return any(w in (text or "") for w in INTERRUPTED_WORDS) and not is_network_problem(text)


BLOCKED_WORDS = ("billing", "PERMISSION_DENIED", "(403)", "trial", "account has been", "spend cap", "SERVICE_DISABLED")


def is_blocked(text: str) -> bool:
    """Google refusing the voice for an account reason (billing, trial credit, spend cap): not the Reel's fault, and retrying cannot help."""
    low = (text or "").lower()
    return any(w.lower() in low for w in BLOCKED_WORDS) and "daily_voice_quota" not in low


def is_network_problem(text: str) -> bool:
    return any(w in (text or "") for w in NETWORK_WORDS)


def network_up(hosts=("generativelanguage.googleapis.com", "aiplatform.googleapis.com", "api.telegram.org")) -> bool:
    import socket
    try:
        for h in hosts:
            socket.getaddrinfo(h, 443)
        return True
    except OSError:
        return False


def wait_for_network(max_seconds: int = 3 * 3600, step: int = 60, up=network_up, sleep=None) -> bool:
    """A morning launch can fire while the Mac's Wi-Fi is still coming back: wait for DNS instead of failing every Reel in one second."""
    import time
    sleep = sleep or time.sleep
    waited = 0
    while not up():
        if waited >= max_seconds:
            return False
        sleep(step); waited += step
    return True


DONE = Path.home() / "arthvan-social" / "logs" / "production-done.json"
VOICE_MODELS = Path.home() / "arthvan-social" / "logs" / "voice-models.json"       # {"backups": ["gemini-3.8-flash-tts", ...]}: only exists once the founder has approved them


def voice_models(path: Path = VOICE_MODELS) -> list:
    """[None, backup1, ...]: None is the normal voice model. A backup is used only when the one before it has no allowance left today,
    and a whole Reel is always voiced by ONE model so its voice never changes halfway."""
    try:
        d = json.loads(Path(path).read_text())
        if float(d.get("cap_inr", 0)) <= tts.extra_spend():          # the approved amount is used up: normal voice only
            return [None]
        return [None] + [m for m in d.get("backups", []) if isinstance(m, str)]
    except (OSError, ValueError, AttributeError):
        return [None]


def quota_day(now=None) -> str:
    """Google's free voice allowance runs on the US Pacific calendar day."""
    from zoneinfo import ZoneInfo
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()


def day_is_done(marker: Path = DONE, now=None) -> bool:
    try:
        return json.loads(Path(marker).read_text()).get("day") == quota_day(now)
    except (OSError, ValueError):
        return False


def mark_day_done(reason: str, marker: Path = DONE, now=None) -> None:
    Path(marker).parent.mkdir(parents=True, exist_ok=True)
    Path(marker).write_text(json.dumps({"day": quota_day(now), "reason": reason}))


def _log(entry: dict, log: Path = LOG) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps(dict(entry, at=datetime.now(timezone.utc).isoformat(timespec="seconds"))) + "\n")


def _failures(log: Path = LOG) -> dict:
    n = {}
    if Path(log).exists():
        for line in Path(log).read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("status") == "failed":
                n[e["id"]] = n.get(e["id"], 0) + 1
            elif e.get("status") == "made":
                n.pop(e["id"], None)
    return n


def _stories(root: Path) -> list:
    held = {s["id"] for s in calendar_plan.load_stories(root) if s["problems"]}
    return [dict(json.loads(p.read_text()), _held=json.loads(p.read_text())["id"] in held) for p in sorted((root / "stories").glob("*.json"))]


def pending_english(root: Path = ROOT) -> list:
    """Scripted English Reels with no finished video, claim-checked and with all their pictures present."""
    from .story import missing_pictures
    done = {p.stem for p in (root / "stories" / "out").glob("*.mp4")}
    out = [s for s in _stories(root) if s.get("lang", "en").split("-")[0] == "en" and s["id"] not in done and not s["_held"] and not missing_pictures(s)]
    return sorted(out, key=lambda s: s.get("post_on", "9999"))


def backlog(root: Path = ROOT, failures: dict = None) -> list:
    """[(lang, english story)] still to convert, in priority order. Only English Reels that are finished and whose shots are all cached."""
    from .story import shot_plan
    failures = _failures() if failures is None else failures
    done = {p.stem for p in (root / "stories" / "out").glob("*.mp4")}
    english = [s for s in _stories(root) if s.get("lang", "en").split("-")[0] == "en" and s["id"] in done and not s["_held"]
               and not any("native" in sc for sc in s["scenes"]) and all(c for (_i, _p, _r, c) in shot_plan(s))]
    english.sort(key=lambda s: (s.get("post_on", "9999"), s["app"]))
    items = []
    for lang in PRIORITY:
        for s in english:
            lid = localize.localized_id(s["id"], lang)
            if s.get("feature") in library.INDIA_ONLY_FEATURES and lang not in library.INDIAN_LANGS:
                continue                                                  # the CA portal, schemes and the business network exist only in India
            if lang in SUPPORTED.get(s["app"], ()) and lid not in done and failures.get(lid, 0) < MAX_TRIES:
                items.append((lang, s))
    return items


def _seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


def build_story(story_path: Path, root: Path = ROOT, extra_env: dict = None, timeout: int = 1500):
    """Render one story into stories/out. Returns (status, message): made | quota | failed."""
    env = dict(os.environ, TTS_NO_WAIT="1", **(extra_env or {}))
    try:
        r = subprocess.run([sys.executable, "-m", "engine.story", str(story_path), str(root / "stories" / "out")], cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "failed", f"render ran over {timeout // 60} minutes"
    text = (r.stdout or "") + (r.stderr or "")
    if "DAILY_VOICE_QUOTA" in text:
        return "quota", "voice allowance used up"
    if r.returncode != 0:
        last = (text.strip().splitlines() or ["no output"])[-1][:160]
        return ("network" if is_network_problem(text[-1500:]) else "blocked" if is_blocked(text[-1500:]) else
                "interrupted" if is_interrupted(text[-1500:]) else "failed"), last
    return "made", ""


def _lines(story: dict) -> int:
    return len(story["scenes"])


def run(root: Path = ROOT, *, dry: bool = False, wait_net=lambda: wait_for_network(900), budget: int = VOICE_BUDGET, build=build_story, ask=None, now: date = None, send=notify.send, log: Path = LOG) -> dict:
    now = now or (datetime.now(timezone.utc) + timedelta(hours=1)).date()
    apps = load_apps()
    result = {"made": [], "failed": [], "stopped": "", "english": 0}
    used = 0

    models = voice_models()
    model_at = {"i": 0}
    budget = budget * len(models)                             # each approved voice model has its own daily allowance

    def build_voiced(path, root_, env=None):
        while True:
            e = dict(env or {})
            if models[model_at["i"]]:
                e["TTS_MODEL"] = models[model_at["i"]]
            status, msg = build(path, root_, e)
            if status == "quota" and model_at["i"] + 1 < len(models):
                model_at["i"] += 1; continue                  # this model is used up for today: make the whole Reel again with the next one
            return status, msg

    def build_net(*a):
        status, msg = build_voiced(*a)
        if status == "network" and wait_net():
            status, msg = build_voiced(*a)
        for _ in range(2):                                    # a sleep woke the page timeouts: voice and shots are cached, so a retry is cheap
            if status != "interrupted":
                break
            status, msg = build_voiced(*a)
        return status, msg

    def finish():
        left = len(backlog(root, _failures(log)))
        result["left"], result["pending_english"] = left, len(pending_english(root))
        return result

    apps_cfg = {k: apps[k] for k in SUPPORTED}
    deferred = []

    def english_phase():
        """English originals whose shots are already filmed (or still affordable). Those that would need NEW paid shots wait for the cut-out phase."""
        nonlocal used
        for s in pending_english(root):
            cost = sum(1 for p in __import__("engine.story", fromlist=["shot_plan"]).shot_plan(s) if not p[3]) * 8 * broll.INR_PER_SECOND
            film_ok = now <= broll.DEADLINE and broll.spent_inr() + cost <= broll.CREDIT_INR - 300
            if cost and not film_ok:
                deferred.append(s); continue
            if used + _lines(s) > budget:
                result["stopped"] = "voice budget"; return
            if dry:
                result["made"].append((s["id"], "English")); used += _lines(s); continue
            status, msg = build_net(root / "stories" / (s["id"].replace("-", "_") + ".json"), root, {})
            _log({"id": s["id"], "status": status, "note": msg, "kind": "english"}, log)
            if status == "network":
                result["stopped"] = "network"; return
            if status == "blocked":
                result["stopped"] = "google blocked the voice (billing or credit?)"; return
            used += _lines(s)
            if status == "quota":
                result["stopped"] = "voice allowance"; return
            (result["made"] if status == "made" else result["failed"]).append((s["id"], msg)); result["english"] += status == "made"

    def conversion_phase():
        nonlocal used
        for lang, base in backlog(root, _failures(log)):
            if used + _lines(base) > budget:
                result["stopped"] = "voice budget"; return
            lid = localize.localized_id(base["id"], lang)
            if dry:
                result["made"].append((lid, library.LANGUAGES.get(lang, lang))); used += _lines(base); continue
            try:
                tr_path = translator.ensure_files(base, base["app"], apps_cfg[base["app"]], lang, root, ask or __import__("engine.gemini", fromlist=["ask"]).ask)
                tr = json.loads(tr_path.read_text())
                if tr.get("machine_translated") and "post_on" not in tr:        # a conversion comes at least a month after its English twin
                    tr["post_on"] = (date.fromisoformat(base.get("post_on", now.isoformat())) + timedelta(days=30)).isoformat()
                    tr_path.write_text(json.dumps(tr, indent=1, ensure_ascii=False) + "\n")
                story = localize.localize(base, tr, lang)
                sp = root / "stories" / (lid.replace("-", "_") + ".json"); sp.write_text(json.dumps(story, indent=1, ensure_ascii=False) + "\n")
            except Exception as e:
                if is_network_problem(f"{type(e).__name__} {e}"):
                    _log({"id": lid, "status": "network", "note": f"translation: {str(e)[:150]}", "kind": "translate"}, log); result["stopped"] = "network"; return
                _log({"id": lid, "status": "failed", "note": f"translation: {str(e)[:150]}", "kind": "translate"}, log); result["failed"].append((lid, f"translation: {str(e)[:90]}")); continue
            status, msg = build_net(sp, root)
            if status == "network":
                _log({"id": lid, "status": "network", "note": msg, "kind": "convert", "lang": lang}, log); result["stopped"] = "network"; return
            if status == "blocked":
                _log({"id": lid, "status": "blocked", "note": msg, "kind": "convert", "lang": lang}, log); result["stopped"] = "google blocked the voice (billing or credit?)"; return
            used += _lines(base)
            if status == "made":
                secs = _seconds(root / "stories" / "out" / f"{lid}.mp4")
                if secs > MAX_SECONDS and tr.get("machine_translated"):          # too long for a Story: one stricter, shorter translation
                    translator.ensure_files(base, base["app"], apps_cfg[base["app"]], lang, root, ask or __import__("engine.gemini", fromlist=["ask"]).ask, strict=True)
                    tr = json.loads(tr_path.read_text()); sp.write_text(json.dumps(localize.localize(base, tr, lang), indent=1, ensure_ascii=False) + "\n")
                    status, msg = build(sp, root); secs = _seconds(root / "stories" / "out" / f"{lid}.mp4") if status == "made" else secs
                if status == "made" and secs > MAX_SECONDS:
                    msg = f"made but {secs:.0f} s, over the 60 s Story limit: held back from posting"
            _log({"id": lid, "status": status, "note": msg, "kind": "convert", "lang": lang}, log)
            if status == "quota":
                result["stopped"] = "voice allowance"; return
            (result["made"] if status == "made" else result["failed"]).append((lid, msg))

    def cutout_phase():
        """English originals that now need new paid shots: the free cut-out style, last."""
        nonlocal used
        for s in deferred:
            if used + _lines(s) > budget:
                result["stopped"] = "voice budget"; return
            if dry:
                result["made"].append((s["id"], "English, free cut-out style")); used += _lines(s); continue
            status, msg = build_net(root / "stories" / (s["id"].replace("-", "_") + ".json"), root, {"REEL_STYLE": "cutout"})
            _log({"id": s["id"], "status": status, "note": msg, "kind": "english"}, log)
            if status == "network":
                result["stopped"] = "network"; return
            if status == "blocked":
                result["stopped"] = "google blocked the voice (billing or credit?)"; return
            used += _lines(s)
            if status == "quota":
                result["stopped"] = "voice allowance"; return
            (result["made"] if status == "made" else result["failed"]).append((s["id"], msg)); result["english"] += status == "made"

    # Order (founder, 15 Oct): while a whole new filmed Reel is still affordable, English originals first; once the video credit
    # is used up, convert the finished Reels into the other languages first, then the remaining English ones (filmed-ready, then cut-out).
    credit_gone = now > broll.DEADLINE or broll.spent_inr() + 6 * 8 * broll.INR_PER_SECOND > broll.CREDIT_INR - 300
    for phase in ([conversion_phase, english_phase, cutout_phase] if credit_gone else [english_phase, conversion_phase, cutout_phase]):
        phase()
        if result["stopped"]:
            break
    if not dry:
        library.sync(library.LIBRARY, root)
    return finish()


def summary(result: dict, credit_line: str = "") -> str:
    by = {}
    for sid, _ in result["made"]:
        lang = sid.rsplit("-", 1)[-1]; by[lang] = by.get(lang, 0) + 1
    names = ", ".join(f"{library.LANGUAGES.get(k, k)} {v}" for k, v in by.items()) or "nothing"
    lines = [f"🎬 Daily production: {len(result['made'])} Reels made ({names}).", f"English originals still to make: {result['pending_english']}. Conversions still to do: {result['left']} (about {max(1, round(result['left'] / 12))} days)."]
    if result["failed"]:
        lines.append(f"Problems: {len(result['failed'])}, for example {result['failed'][0][0]}: {result['failed'][0][1]}")
    if result["stopped"]:
        lines.append(f"Stopped for today: {result['stopped']}. It carries on " + ("at the next run, once the connection is back." if result["stopped"] == "network" else "tomorrow by itself."))
    if credit_line:
        lines.append(credit_line)
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry = "--dry" in argv
    resume = "--resume" in argv                 # started every few minutes by a second launch agent: picks the work up again whenever the Mac wakes
    if resume and day_is_done():
        return 0
    busy = subprocess.run(["pgrep", "-f", "scratchpad/pipeline"], capture_output=True, text=True).stdout.strip()
    if busy and not dry:
        print("another production queue is running; nothing to do now"); return 0
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if not resume:
            print("a production run is already going")
        return 0
    if not dry and not wait_for_network():
        print("no network for 3 hours; nothing made today"); return 0
    result = run(dry=dry)
    blocked = result["stopped"].startswith("google blocked")
    if not dry and (result["stopped"] in ("voice allowance", "voice budget") or blocked):
        mark_day_done(result["stopped"])        # the day's voice is used (or Google blocked it): resume launches stay quiet until the next Pacific day
    text = summary(result, notify.credit_line())
    print(text)
    if dry:
        for sid, what in result["made"][:40]:
            print("  would make", sid, "|", what)
        return 0
    if resume and not result["made"] and not blocked:           # a resume launch that made nothing says nothing (except a Google block: the founder must hear it once)
        return 0
    notify.send(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
