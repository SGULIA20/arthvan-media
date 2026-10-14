"""Character story ads: voice (Gemini TTS, or macOS say when "tts" is "say") + animated scenes (Playwright) + music + subtitles → MP4.

python -m engine.story stories/lumi_friday_hi.json out_dir
"""
import json, os, re, shutil, subprocess, sys, tempfile, wave
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

from .config import ROOT, load_apps
from .music import synth, write_m4a
from .tts import gemini_clip, pick_voice
from . import broll

TEMPLATE = ROOT / "engine" / "templates" / "story2.html"
CHAR_DIR = ROOT / "engine" / "assets" / "characters"
BADGE = ROOT / "engine" / "assets" / "google-play-badge.png"
FPS = 30


# An image that has already FAILED (complete but no width) never fires load or error again, so waiting for it would freeze the render for ever
# (14 Oct: lumi-accountant-file-en sat at 0% CPU for 20+ minutes). Broken images count as done, and the whole wait is capped at 5 s.
WAIT_IMAGES = ("Promise.race([Promise.all([...document.images].map(i => (i.complete && i.naturalWidth) "
               "? (i.decode ? i.decode().catch(() => 0) : 0) : (i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; })))), "
               "new Promise(r => setTimeout(r, 5000))])")
BROKEN_IMAGES = "[...document.images].filter(i => i.complete && !i.naturalWidth).map(i => i.src)"


def blank_frames(frames_dir: Path, ratio: float = 0.55) -> list:
    """Frames whose JPEG is much smaller than BOTH neighbours: an empty frame compresses far smaller than a picture, and a
    real scene change is a ramp, not a one-frame dip. A safety net behind the image wait."""
    sizes = [p.stat().st_size for p in sorted(Path(frames_dir).glob("f*.jpg"))]
    return [i for i in range(1, len(sizes) - 1) if sizes[i] < ratio * min(sizes[i - 1], sizes[i + 1])]


def end_languages(app_cfg: dict) -> dict:
    """The line every Reel's end card shows next to the Play Store badge: how many languages the app speaks, and their names.
    Raises when an app has none configured, so a Reel can never be rendered without it (founder rule 13 Oct 2026)."""
    langs = app_cfg.get("languages") or []
    if not langs:
        raise ValueError(f"{app_cfg.get('name', 'app')} has no languages configured in content/apps.json: every Reel must name them on its end card")
    # each name keeps its dot attached and never splits across lines, so a line can never start with a separator
    line = " ".join(f'<span style="white-space:nowrap">{n}{" ·" if i < len(langs) - 1 else ""}</span>' for i, n in enumerate(langs))
    return {"label": app_cfg.get("languages_phrase", "Available in {n} languages").format(n=len(langs)), "line": line}


def cast_prompt(prompt: str, cast: dict) -> str:
    """{meena} in a shot prompt becomes the cast description, so a supporting character looks the same in every shot."""
    def sub(m):
        name = m.group(1)
        if name not in cast:
            raise KeyError(f"shot prompt names {{{name}}} but the story's cast has no {name}")
        return cast[name]
    return re.sub(r"\{([a-z_]+)\}", sub, prompt)


REELS_FOLDER = Path.home() / "Desktop" / "Arthvan-Reels"


def file_in_reels_folder(mp4: Path, story_id: str, folder: Path = None) -> Path:
    """Every Reel made goes into one folder the founder can open anytime. Numbered in the order made; a Reel already
    in the folder is never replaced or deleted."""
    folder = Path(folder or REELS_FOLDER); folder.mkdir(parents=True, exist_ok=True)
    existing = sorted(folder.glob("*.mp4"))
    for f in existing:
        if f.stem.split("-", 1)[-1] == story_id:
            return f
    nums = [int(f.name.split("-", 1)[0]) for f in existing if f.name.split("-", 1)[0].isdigit()]
    dst = folder / f"{(max(nums) + 1 if nums else 1):02d}-{story_id}.mp4"
    shutil.copy2(mp4, dst)
    return dst


_PRESENT_POSES = ("explaining_right", "phone", "phone_sofa", "curious", "front_standing", "pointing_up", "thinking", "relieved", "listening", "front_happy", "front_neutral")


def cutout_story(story: dict) -> dict:
    """The in-house style of the first Reels (cut-out character on a gradient with the real app screens), made from a
    filmed story: no Veo shots are needed. A scene with a screen becomes a 'present' scene, a scene without becomes a
    'scene' with its card, the first scene a talking head, the end card stays."""
    import copy
    st = copy.deepcopy(story); who = st["character"]; n = 0
    have = lambda pose: (CHAR_DIR / f"{who}_{pose}.png").exists()
    poses = [p for p in _PRESENT_POSES if have(p)] or ["front_neutral"]
    for i, sc in enumerate(st["scenes"]):
        if sc.get("layout") != "clip":
            continue
        if i == 0 and have("head_neutral"):
            sc["layout"] = "talk"; sc["pose"] = "head_neutral"
        elif sc.get("screen"):
            sc["layout"] = "present"; sc["pose"] = poses[n % len(poses)]; n += 1
        else:
            sc["layout"] = "scene"; sc["pose"] = poses[n % len(poses)]; n += 1
            sc.setdefault("card", sc.get("title") or "")
        sc.pop("clip", None); sc.pop("refs", None); sc["min"] = min(sc.get("min", 6), 7)
    st.pop("cast", None); st["style"] = "cutout"
    return st


def prefetch_shots(story: dict, workers: int = 3) -> int:
    """Make all of a story's missing shots up to `workers` at a time (the ledger is lock-safe), so a Reel takes about as
    long as its slowest shot, not the sum. Returns how many were made. A shot Veo declines names its scene."""
    from concurrent.futures import ThreadPoolExecutor
    todo, seen = [], set()
    for i, prompt, refs, cached in shot_plan(story):
        key = broll.key_for(prompt, 8, references=refs or None)
        if not cached and key not in seen:
            seen.add(key); todo.append((i, prompt, refs))
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=min(workers, len(todo))) as ex:
        futs = [(i, prompt, ex.submit(broll.clip, prompt, references=refs or None)) for i, prompt, refs in todo]
        for i, prompt, fut in futs:
            try:
                fut.result()
            except broll.BRollFiltered as e:
                raise SystemExit(f"scene {i} of {story['id']}: Veo declined the shot prompt, rephrase it: {prompt[:90]} ({e})")
    return len(todo)


def film_available() -> bool:
    """New Veo shots can only be made while the Google trial credit lasts (see engine.broll)."""
    return not broll.pace()["finished"]


def shot_plan(story: dict) -> list:
    """Every filmed shot a story needs: (scene number, prompt, reference pictures, cached?). Reading only, spends nothing."""
    out = []
    for i, sc in enumerate(story["scenes"]):
        if sc.get("clip"):
            refs = [broll.reference_picture(c) for c in sc.get("refs", [])]
            prompt = cast_prompt(sc["clip"], story.get("cast", {}))
            cached = (broll.BROLL_DIR / f"{broll.key_for(prompt, 8, references=refs or None)}.mp4").exists()
            out.append((i, prompt, refs, cached))
    return out


def price_line(story: dict) -> str:
    plan = shot_plan(story); new = [p for p in plan if not p[3]]
    return (f"{story['id']}: {len(plan)} filmed shots, {len(plan) - len(new)} already made, {len(new)} new "
            f"= about ₹{round(len(new) * 8 * broll.INR_PER_SECOND)} of credit. {broll.status_line()}")


def voice_clip(text: str, voice: str, rate: int, out_wav: Path) -> float:
    aiff = out_wav.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "44100", "-ac", "2", str(out_wav)], check=True)
    with wave.open(str(out_wav)) as w:
        return w.getnframes() / w.getframerate()


def missing_pictures(story: dict, root: Path = None) -> list:
    """Pictures a script names that do not exist: character poses and phone screens. Checked before anything is generated."""
    root = Path(root) if root else ROOT
    char_dir = root / "engine" / "assets" / "characters"
    lang = story.get("lang", "en").split("-")[0]                       # same rule as the renderer: hi-IN looks in the hi folder
    shots = root / "store" / "shots" / story["app"] / lang
    if not shots.exists():
        shots = root / "store" / "shots" / story["app"]
    out = []
    for i, sc in enumerate(story["scenes"]):
        if sc.get("pose") and not sc.get("who") and not (char_dir / f"{story['character']}_{sc['pose']}.png").exists():
            out.append(f"scene {i}: no picture of {story['character']} in the pose '{sc['pose']}'")
        if sc.get("screen") and not any((d / sc["screen"]).exists() for d in (shots, root / "store" / "shots" / story["app"] / "en", root / "store" / "shots" / story["app"])):
            out.append(f"scene {i}: screen {sc['screen']} not found")
    return out


def build(story_path: Path, out_dir: Path) -> Path:
    story = json.loads(Path(story_path).read_text())
    problems = missing_pictures(story)
    if problems:
        raise SystemExit(f"{story['id']}: cannot render, {'; '.join(problems)}")
    plan = shot_plan(story)
    if plan and (os.environ.get("REEL_STYLE") == "cutout" or (any(not c for (_i, _p, _r, c) in plan) and not film_available())):
        print("film shots are not available (or REEL_STYLE=cutout): making the cut-out style Reel", flush=True)
        story = cutout_story(story)
    else:
        print(price_line(story), flush=True)
    app = load_apps()[story["app"]]
    app = {**app, **(app.get("i18n") or {}).get(story.get("lang", "en").split("-")[0], {})}      # a language's own end-card texts (content/apps.json i18n)
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 1. voice per scene; scene length = max(min, voice + 1.2 s)
        clips = []
        for i, s in enumerate(story["scenes"]):
            wav = tmp / f"vo{i}.wav"
            if story.get("tts", "gemini") == "say":
                d = voice_clip(s["vo"], s.get("voice", story["voice"]), s.get("rate", story.get("rate", 175)), wav)
            else:
                d = gemini_clip(s["vo"], pick_voice({"character": story["character"], "voice": s.get("voice")}), wav)
            s["dur"] = round(max(s.get("min", 4), d + 1.2), 2)
            clips.append((wav, d))
        total = sum(s["dur"] for s in story["scenes"])
        # voice loudness per frame (drives the mouth): lay the clips on the timeline first
        sr = 44100
        vo = np.zeros((int(total * sr) + sr, 2), dtype=np.float32)
        t0 = 0.0
        for s, (wav, d) in zip(story["scenes"], clips):
            with wave.open(str(wav)) as w:
                a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32).reshape(-1, 2) / 32768
            start = int((t0 + 0.4) * sr); vo[start:start + len(a)] += a * 0.95; t0 += s["dur"]
        vo = vo[: int(total * sr)]
        hop = sr // FPS
        raw = np.array([float(np.sqrt(np.mean(vo[i:i + hop, 0] ** 2))) for i in range(0, len(vo), hop)])
        raw = raw / (raw.max() or 1.0)
        # mouth timing: smooth, then open on syllables with hysteresis and a minimum hold, so it reads as speech
        sm = np.convolve(raw, np.ones(3) / 3, mode="same")
        env, opened, hold = [], False, 0
        for v in sm:
            if opened:
                hold += 1
                if v < 0.12 and hold >= 4: opened = False
            elif v > 0.22:
                opened, hold = True, 0
            env.append(1.0 if opened else 0.0)
        env = [round(float(e), 1) for e in env]
        # per-frame loudness (0..1, lightly smoothed) so the mouth opens with the syllable's energy, not a fixed flap
        amp = np.convolve(raw, np.ones(2) / 2, mode="same")
        amp = [round(float(min(1.0, a * 1.25)), 2) for a in amp]
        # screens in the ad's language when captured, else English
        lang = story.get("lang", "en").split("-")[0]
        shots = ROOT / "store" / "shots" / story["app"] / lang
        if not shots.exists():
            shots = ROOT / "store" / "shots" / story["app"]
        elif shots.name == lang and lang != "en":                       # a language folder may hold only some screens: the rest come from English
            for sc in story["scenes"]:
                name = sc.get("screen")
                if name and not (shots / name).exists() and (ROOT / "store" / "shots" / story["app"] / "en" / name).exists():
                    sc["screen"] = "../en/" + name
        # 2. frames
        deck = {"scenes": story["scenes"], "title": story["title"], "end_line": app["end_line"], "app_name": app["name"],
                "palette": app["palette"], "chars": story["character"], "char_base": CHAR_DIR.as_uri(), "vo_env": env, "vo_amp": amp,
                "disclaimer": app.get("money_disclaimer") or "", "link_in_bio": app.get("link_in_bio", "Link in bio"), "icon": (ROOT / app["icon"]).as_uri(),
                "badge": BADGE.as_uri(), "shots": shots.as_uri(), "langs": end_languages(app)}
        clips = {}
        prefetch_shots(story)
        for i, s in enumerate(story["scenes"]):
            if s.get("clip"):
                refs = [broll.reference_picture(c) for c in s.get("refs", [])]
                prompt = cast_prompt(s["clip"], story.get("cast", {}))
                try:
                    mp4 = broll.clip(prompt, references=refs or None)
                except broll.BRollFiltered as e:
                    raise SystemExit(f"scene {i} of {story['id']}: Veo declined the shot prompt, rephrase it: {s['clip'][:90]} ({e})")
                d = tmp / f"clip{i}"
                clips[str(i)] = {"dir": d.as_uri(), "n": broll.frames(mp4, d, FPS)}
        deck["clips"] = clips
        frames = tmp / "frames"; frames.mkdir()
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1080, "height": 1920})
            pg.add_init_script("window.STORY=" + json.dumps(deck) + ";")
            pg.goto(TEMPLATE.as_uri()); pg.evaluate("document.fonts.ready")
            pg.wait_for_function("[...document.images].every(i => i.complete)"); pg.wait_for_timeout(200)
            n = int(round(total * FPS))
            for f in range(n):
                pg.evaluate(f"render({f / FPS})")
                # every frame rebuilds the page, so a filmed frame is a brand-new <img>: wait until it is loaded AND decoded,
                # otherwise the screenshot catches an empty frame and the video blinks (measured 13 Oct: 60+ dark frames per Reel)
                pg.evaluate(WAIT_IMAGES)
                if f % 120 == 0:
                    broken = pg.evaluate(BROKEN_IMAGES)
                    if broken:
                        print(f"warning: broken image at frame {f}: {broken[0][-90:]}", flush=True)
                pg.screenshot(path=str(frames / f"f{f:04d}.jpg"), type="jpeg", quality=92)
            b.close()
        blank = blank_frames(frames)
        if blank:
            print(f"note: {len(blank)} frames looked empty and were repeated from the previous frame", flush=True)
            for f in blank:
                shutil.copy(frames / f"f{f - 1:04d}.jpg", frames / f"f{f:04d}.jpg")
        # 3. music underneath the voice (ducked)
        music = synth(story["app"], 7, total) * 0.28
        n = min(len(vo), len(music))
        mix = np.clip(vo[:n] + music[:n], -0.98, 0.98)
        audio = tmp / "mix.m4a"; write_m4a(mix, audio)
        out = out_dir / f"{story['id']}.mp4"
        # encode to a private temp file, check the WHOLE file decodes, and only then move it into place: a second render of the
        # same story, a crash or a full disk can never leave a damaged Reel (13 Oct: lumi-scan-en was corrupted by two queues)
        part = out.with_name(f".{out.stem}.{os.getpid()}.part.mp4")
        for attempt in (1, 2):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "f%04d.jpg"), "-i", str(audio),
                            "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-maxrate", "1700k", "-bufsize", "3400k", "-pix_fmt", "yuv420p", "-r", str(FPS),
                            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(part)], check=True)
            from .qa import decode_errors
            bad = decode_errors(part)
            if bad == 0:
                break
            print(f"encode attempt {attempt}: {bad} decoder complaints, retrying", flush=True)
        else:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"{story['id']}: the encoded video is damaged after two attempts; nothing was written")
        part.replace(out)
        print(f"{out} {total:.1f}s")
        try:
            from .qa import blink_count
            blinks = blink_count(out)
            print(f"blink check: {blinks} single-frame flashes" + ("  <-- TOO MANY, do not post" if blinks > 12 else "  (good)"), flush=True)
        except Exception as e:                                   # a QA failure never stops a render
            print("blink check skipped:", e)
        try:
            if os.environ.get("REELS_FOLDER_OFF"):
                return out
            print("filed in", file_in_reels_folder(out, story["id"]))
        except OSError as e:
            print("could not file in the Reels folder:", e)
        return out


if __name__ == "__main__":
    if sys.argv[1] == "--plan":          # price check, spends nothing: python -m engine.story --plan stories/x.json ...
        for f in sys.argv[2:]:
            print(price_line(json.loads(Path(f).read_text())))
    else:
        build(Path(sys.argv[1]), Path(sys.argv[2]))
