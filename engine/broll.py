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
INR_PER_SECOND = 7.0
STYLE = "Cinematic 3D animated film style, warm light, shallow depth of field, slow camera move, no text, no logos, no captions. "
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class BRollError(Exception):
    pass


class BRollFiltered(BRollError):
    """Veo's content filter declined this prompt: skip it, never retry it, carry on with the next."""


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


def _call(method, url, token, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read()[:300].decode(errors="replace")}


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
        st, b = _call("POST", f"{base}:fetchPredictOperation", token, {"operationName": op})
        if st != 200:
            raise BRollError(f"Veo poll failed ({st}): {str(b)[:200]}")
        if b.get("done"):
            vids = (b.get("response") or {}).get("videos") or []
            if vids and vids[0].get("bytesBase64Encoded"):
                return base64.b64decode(vids[0]["bytesBase64Encoded"])
            resp = b.get("response") or {}
            if resp.get("raiMediaFilteredCount"):
                raise BRollFiltered("content filter: " + "; ".join(resp.get("raiMediaFilteredReasons") or ["no reason given"])[:200])
            raise BRollError("Veo finished without a video: " + str(b)[:300])
    raise BRollError("Veo took longer than 15 minutes")


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


def spent_inr(ledger_path: Path = LEDGER) -> float:
    return float(_ledger(ledger_path).get("spent_inr", 0.0))


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


def clip(prompt: str, *, seconds: int = 8, references: list = None, cache: Path = BROLL_DIR, ledger_path: Path = LEDGER,
         credit: float = CREDIT_INR, generate=_generate, token: str = None, today: date = None, library: Path = None) -> Path:
    """The cached MP4 for this prompt (and reference pictures), generating it, charging the rupee ledger and filing a
    readable copy in the library only when it does not exist yet."""
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{key_for(prompt, seconds, references=references)}.mp4"
    if out.exists():
        return out
    today = today or date.today()
    led = _ledger(ledger_path); spent = float(led.get("spent_inr", 0.0)); cost = seconds * INR_PER_SECOND
    if today > DEADLINE:
        raise BRollError("the Google Cloud trial credit expired on 10 Dec 2026: no more shots, nothing is charged")
    if spent + cost > credit:
        raise BRollError(f"the video credit is finished: ₹{spent:.0f} of ₹{credit:.0f} used; no more shots, nothing is charged")
    key = out.stem
    if key in led.get("filtered", []):
        raise BRollFiltered("this prompt was declined by the content filter before; not retried")
    try:
        data = generate(STYLE + prompt, seconds, token if token is not None else access_token(), references=references) if references \
            else generate(STYLE + prompt, seconds, token if token is not None else access_token())
    except BRollFiltered:
        led.setdefault("filtered", []).append(key)
        Path(ledger_path).parent.mkdir(parents=True, exist_ok=True); Path(ledger_path).write_text(json.dumps(led, indent=1))
        raise
    out.write_bytes(data)
    try:
        file_in_library(out, prompt, references, library)
    except OSError:
        pass
    led["spent_inr"] = round(spent + cost, 2)
    led["seconds"] = int(led.get("seconds", 0)) + seconds
    led.setdefault("shots", []).append({"day": today.isoformat(), "seconds": seconds, "inr": cost, "key": out.stem, "prompt": prompt[:120],
                                        "refs": [Path(r).name for r in (references or [])]})
    Path(ledger_path).parent.mkdir(parents=True, exist_ok=True)
    Path(ledger_path).write_text(json.dumps(led, indent=1))
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
