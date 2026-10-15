"""Short cinematic shots (B-roll) for the stories, generated once by Veo on Vertex AI and cached by prompt, with a
monthly cap on generated seconds enforced here, in code, on top of the Cloud budget alerts.
Auth is the founder's gcloud sign-in on this Mac; rendering never happens in CI."""
import base64
import hashlib
import re
import json
import os
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from .config import ROOT

PROJECT = "gen-lang-client-0135966425"
LOCATION = "us-central1"
MODEL = "veo-3.1-fast-generate-001"
BROLL_DIR = ROOT / "stories" / "broll"
LEDGER = BROLL_DIR / "ledger.json"
LIBRARY = Path.home() / "arthvan-social" / "shots"          # readable copies: <slug>.mp4 + index.md with the prompts
# Founder's rule (12 Oct 2026): spend the Google Cloud trial credit on video, all of it, before it expires on
# 10 Dec 2026; then STOP and tell him. Never a paid run. The ledger below is the code-side stop; Cloud budget alerts
# are the second line of defence. INR_PER_SECOND is the Veo 3.1 Fast (720p, no audio) list price in rupees; adjust
# here if the bill shows otherwise.
CREDIT_INR = 28000.0
DEADLINE = date(2026, 12, 10)
START = date(2026, 10, 12)
INR_PER_SECOND = 8.5      # measured 13 Oct: ₹7,744 billed for 120 shots (₹8.1/s) + headroom for billing lag
STYLE = "Cinematic 3D animated film style, warm light, shallow depth of field, slow camera move, no text, no logos, no captions. "
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class BRollError(Exception):
    pass


class BRollFiltered(BRollError):
    """Veo's content filter declined this prompt: skip it, never retry it, carry on with the next."""


class BRollLost(BRollError):
    """The job was accepted by Veo but the clip never reached us (timeout, dropped connection): it may still be billed."""


class BRollBadReference(BRollError):
    """Veo refused a reference picture: make the shot from the description alone."""


def gcloud() -> str:
    for p in (shutil.which("gcloud"), Path.home() / "google-cloud-sdk-dl" / "google-cloud-sdk" / "bin" / "gcloud", Path.home() / "google-cloud-sdk" / "bin" / "gcloud"):
        if p and Path(p).exists():
            return str(p)
    raise BRollError("gcloud is not installed on this Mac")


def access_token() -> str:
    try:
        return subprocess.run([gcloud(), "auth", "print-access-token"], check=True, capture_output=True, text=True).stdout.strip()
    except subprocess.CalledProcessError as e:
        raise BRollError("gcloud is not signed in: run  gcloud auth login --update-adc") from e


class _Token:
    """gcloud access tokens live about an hour; a long batch outlives one, so fetch again on a 401."""
    def __init__(self, fixed=None): self.fixed, self.value = fixed, fixed
    def get(self):
        if self.value is None: self.value = access_token()
        return self.value
    def refresh(self):
        if self.fixed is None: self.value = access_token()


def _call(method, url, token, body=None, tries: int = 4):
    import http.client
    tok = token if isinstance(token, _Token) else _Token(token)
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, method=method,
                                     headers={"Authorization": f"Bearer {tok.get()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600, context=_CTX) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            text = e.read()[:300].decode(errors="replace")
            if e.code == 401 and attempt < tries - 1:
                tok.refresh(); continue
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(20 * (attempt + 1)); continue
            return e.code, {"error": text}
        except (TimeoutError, http.client.IncompleteRead, urllib.error.URLError, ConnectionError, OSError) as e:
            last = e
            if attempt < tries - 1:
                time.sleep(15 * (attempt + 1)); continue
    raise BRollError(f"Veo request kept failing: {type(last).__name__}: {str(last)[:120]}")


def _generate(prompt: str, seconds: int, token: str, model: str = MODEL, references: list = None) -> bytes:
    base = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}/publishers/google/models/{model}"
    inst = {"prompt": prompt}
    if references:
        inst["referenceImages"] = [{"image": {"bytesBase64Encoded": base64.b64encode(Path(r).read_bytes()).decode(),
                                              "mimeType": "image/png" if str(r).lower().endswith(".png") else "image/jpeg"},
                                    "referenceType": "asset"} for r in references[:3]]
    st, body = _call("POST", f"{base}:predictLongRunning", token,
                     {"instances": [inst],
                      "parameters": {"aspectRatio": "9:16", "durationSeconds": seconds, "sampleCount": 1, "generateAudio": False, "resolution": "720p"}})
    if st != 200:
        raise BRollError(f"Veo refused ({st}): {str(body)[:200]}")
    op = body["name"]; t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(15)
        try:
            st, b = _call("POST", f"{base}:fetchPredictOperation", token, {"operationName": op})
        except BRollError as e:
            raise BRollLost(str(e)) from e
        if st != 200:
            raise BRollLost(f"Veo poll failed ({st}): {str(b)[:200]}")
        if b.get("done"):
            err = b.get("error") or {}
            if "input image" in str(err.get("message", "")).lower():
                raise BRollBadReference(str(err.get("message"))[:200])
            vids = (b.get("response") or {}).get("videos") or []
            if vids and vids[0].get("bytesBase64Encoded"):
                return base64.b64decode(vids[0]["bytesBase64Encoded"])
            resp = b.get("response") or {}
            if resp.get("raiMediaFilteredCount"):
                raise BRollFiltered("content filter: " + "; ".join(resp.get("raiMediaFilteredReasons") or ["no reason given"])[:200])
            raise BRollLost("Veo finished without a video: " + str(b)[:300])
    raise BRollLost("Veo took longer than 15 minutes")


def key_for(prompt: str, seconds: int, model: str = MODEL, references: list = None) -> str:
    refs = "|".join(hashlib.sha1(Path(r).read_bytes()).hexdigest()[:12] for r in (references or []))
    return hashlib.sha1(f"{model}|{seconds}|{STYLE}{prompt}|{refs}".encode()).hexdigest()


def slug(prompt: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:70]


def file_in_library(out: Path, prompt: str, references: list = None, library: Path = None) -> Path:
    """A readable copy of the clip next to an index of prompts, for browsing and reuse by hand."""
    library = Path(library or LIBRARY); library.mkdir(parents=True, exist_ok=True)
    name = f"{slug(prompt)}-{out.stem[:6]}.mp4"
    shutil.copy(out, library / name)
    with (library / "index.md").open("a") as f:
        f.write(f"- `{name}` — {prompt}" + (f" (refs: {', '.join(Path(r).name for r in references)})" if references else "") + "\n")
    return library / name


def _ledger(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def spent(led: dict) -> float:
    """Rupees used: Google's own figure at the last calibration plus every shot recorded since, else the running total."""
    cal = led.get("calibration")
    if cal:
        return float(cal["billed_inr"]) + sum(float(x.get("inr", 0)) for x in led.get("shots", [])[int(cal["shots_counted"]):])
    return float(led.get("spent_inr", 0.0))


class _Locked:
    """Read-modify-write the ledger under an exclusive file lock, so parallel renders can never overwrite each other."""
    def __init__(self, path: Path): self.path = Path(path)
    def __enter__(self):
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = open(self.path.with_suffix(".lock"), "w"); fcntl.flock(self._lock, fcntl.LOCK_EX)
        self.led = _ledger(self.path); self._before = len(self.led.get("shots", [])); return self.led
    def __exit__(self, et, ev, tb):
        import fcntl
        if et is None:
            if self.led.get("calibration"):
                self.led["spent_inr"] = round(spent(self.led), 2)
            else:       # no calibration yet: the running total grows by the shots recorded in this session
                added = sum(float(x.get("inr", 0)) for x in self.led.get("shots", [])[self._before:])
                self.led["spent_inr"] = round(float(self.led.get("spent_inr", 0.0)) + added, 2)
            tmp = self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(self.led, indent=1)); tmp.replace(self.path)
        fcntl.flock(self._lock, fcntl.LOCK_UN); self._lock.close()


def spent_inr(ledger_path: Path = LEDGER) -> float:
    return spent(_ledger(ledger_path))


def reconcile(ledger_path: Path = LEDGER, cache: Path = BROLL_DIR, seconds: int = 8) -> int:
    """Record every clip file on disk that the ledger does not know (earlier parallel renders overwrote entries)."""
    n = 0
    with _Locked(ledger_path) as led:
        known = {x.get("key") for x in led.get("shots", [])}
        for f in sorted(Path(cache).glob("*.mp4")):
            if f.stem not in known:
                led.setdefault("shots", []).append({"day": date.fromtimestamp(f.stat().st_mtime).isoformat(), "seconds": seconds,
                                                    "inr": seconds * INR_PER_SECOND, "key": f.stem, "prompt": "(reconciled from the file)", "note": "reconciled"})
                n += 1
    return n


def calibrate(billed_inr: float, today: date = None, ledger_path: Path = LEDGER) -> float:
    """Pin the ledger to the figure on Google's Credits page: ₹ used so far on the trial credit, as of now."""
    with _Locked(ledger_path) as led:
        led["calibration"] = {"day": (today or date.today()).isoformat(), "billed_inr": float(billed_inr), "shots_counted": len(led.get("shots", []))}
        total = spent(led)
    return total


def pace(ledger_path: Path = LEDGER, today: date = None, credit: float = CREDIT_INR) -> dict:
    """Where we are against the plan of finishing the credit by the deadline: target so far, actual, days left."""
    today = today or date.today()
    total_days = max(1, (DEADLINE - START).days)
    frac = min(1.0, max(0.0, (today - START).days / total_days))
    return {"target_inr": round(credit * frac), "spent_inr": round(spent_inr(ledger_path)), "days_left": max(0, (DEADLINE - today).days),
            "credit_inr": credit, "finished": spent_inr(ledger_path) >= credit or today > DEADLINE}


def status_line(ledger_path: Path = LEDGER, today: date = None) -> str:
    p = pace(ledger_path, today)
    if p["finished"]:
        return (f"**Veo video credit is FINISHED** (₹{p['spent_inr']} of ₹{int(p['credit_inr'])} used, or the 10 Dec deadline passed). "
                "No more shots will be generated; nothing is charged. Discuss what happens next.")
    return f"Veo video credit: ₹{p['spent_inr']} used of ₹{int(p['credit_inr'])}; on-plan figure for today ₹{p['target_inr']}; {p['days_left']} days to 10 Dec."


def clip(prompt: str, *, seconds: int = 8, references: list = None, cache: Path = BROLL_DIR, **kw) -> Path:
    """The cached MP4 for this prompt (and reference pictures), generating it, charging the rupee ledger and filing a
    readable copy in the library only when it does not exist yet. Two processes asking for the same shot at once (the nightly
    production and a pre-filming run) take turns on a lock file, so the second one finds the shot made and never pays twice."""
    import fcntl
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{key_for(prompt, seconds, references=references)}.mp4"
    if out.exists():
        return out
    locks = cache / ".locks"; locks.mkdir(exist_ok=True)
    with (locks / f"{out.stem}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _clip_once(prompt, seconds=seconds, references=references, cache=cache, **kw)


def _clip_once(prompt: str, *, seconds: int = 8, references: list = None, cache: Path = BROLL_DIR, ledger_path: Path = LEDGER,
               credit: float = CREDIT_INR, generate=_generate, token: str = None, today: date = None, library: Path = None) -> Path:
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{key_for(prompt, seconds, references=references)}.mp4"
    if out.exists():
        return out
    today = today or date.today()
    cost = seconds * INR_PER_SECOND
    if today > DEADLINE:
        raise BRollError("the Google Cloud trial credit expired on 10 Dec 2026: no more shots, nothing is charged")
    key = out.stem
    with _Locked(ledger_path) as led:
        used = spent(led) + float(led.get("reserved_inr", 0.0))
        if key in led.get("filtered", []):
            raise BRollFiltered("this prompt was declined by the content filter before; not retried")
        if used + cost > credit:
            raise BRollError(f"the video credit is finished: ₹{used:.0f} of ₹{credit:.0f} used or reserved; no more shots, nothing is charged")
        led["reserved_inr"] = round(float(led.get("reserved_inr", 0.0)) + cost, 2)
    tok = _Token(token)
    outcome = "error"
    try:
        try:
            if references:
                try:
                    data = generate(STYLE + prompt, seconds, tok, references=references)
                except BRollBadReference:
                    references = None                               # the description alone, then
                    data = generate(STYLE + prompt, seconds, tok)
            else:
                data = generate(STYLE + prompt, seconds, tok)
            outcome = "ok"
        except BRollFiltered:
            outcome = "filtered"; raise
        except BRollLost:
            outcome = "lost"; raise
    finally:
        with _Locked(ledger_path) as led:
            led["reserved_inr"] = round(max(0.0, float(led.get("reserved_inr", 0.0)) - cost), 2)
            if outcome == "ok":
                out.write_bytes(data)
                led["seconds"] = int(led.get("seconds", 0)) + seconds
                led.setdefault("shots", []).append({"day": today.isoformat(), "seconds": seconds, "inr": cost, "key": key, "prompt": prompt[:120],
                                                    "refs": [Path(r).name for r in (references or [])]})
            elif outcome == "filtered":
                led.setdefault("filtered", []).append(key)
            elif outcome == "lost":     # accepted by Veo, never delivered: may be billed, so it counts
                led.setdefault("shots", []).append({"day": today.isoformat(), "seconds": seconds, "inr": cost, "key": None,
                                                    "prompt": prompt[:120], "note": "lost after submission, counted as billed"})
    try:
        file_in_library(out, prompt, references, library)
    except OSError:
        pass
    return out


def frames(mp4: Path, out_dir: Path, fps: int = 30, width: int = 1080, height: int = 1920) -> int:
    """Extract the clip as JPEG frames sized to the story canvas (cover crop). Returns the frame count."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    vf = f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf", vf, "-q:v", "3", str(out_dir / "f%04d.jpg")], check=True)
    return len(list(out_dir.glob("f*.jpg")))


def reference_picture(character: str) -> Path:
    """The picture Veo gets so a character looks like itself: the source photo on white, else the cut-out PNG."""
    base = character.split("_")[0]
    for cand in (Path.home() / "arthvan-social" / "characters" / base / f"{character}_front_neutral.jpg",
                 Path.home() / "arthvan-social" / "characters" / base / f"{character}_front_happy.jpg",
                 ROOT / "engine" / "assets" / "characters" / f"{character}_front_neutral.png",
                 ROOT / "engine" / "assets" / "characters" / f"{character}_front_happy.png"):
        if cand.exists():
            return cand
    raise BRollError(f"no reference picture for {character}")
