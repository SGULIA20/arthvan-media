"""Character story ads: voice (Gemini TTS, or macOS say when "tts" is "say") + animated scenes (Playwright) + music + subtitles → MP4.

python -m engine.story stories/lumi_friday_hi.json out_dir
"""
import json, subprocess, sys, tempfile, wave
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

from .config import ROOT, load_apps
from .music import synth, write_m4a
from .tts import gemini_clip, pick_voice

TEMPLATE = ROOT / "engine" / "templates" / "story2.html"
CHAR_DIR = ROOT / "engine" / "assets" / "characters"
BADGE = ROOT / "engine" / "assets" / "google-play-badge.png"
FPS = 30


def voice_clip(text: str, voice: str, rate: int, out_wav: Path) -> float:
    aiff = out_wav.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "44100", "-ac", "2", str(out_wav)], check=True)
    with wave.open(str(out_wav)) as w:
        return w.getnframes() / w.getframerate()


def build(story_path: Path, out_dir: Path) -> Path:
    story = json.loads(Path(story_path).read_text())
    app = load_apps()[story["app"]]
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
        # 2. frames
        deck = {"scenes": story["scenes"], "title": story["title"], "end_line": app["end_line"], "app_name": app["name"],
                "palette": app["palette"], "chars": story["character"], "char_base": CHAR_DIR.as_uri(), "vo_env": env, "vo_amp": amp,
                "disclaimer": app.get("money_disclaimer") or "", "icon": (ROOT / app["icon"]).as_uri(),
                "badge": BADGE.as_uri(), "shots": shots.as_uri()}
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
                pg.screenshot(path=str(frames / f"f{f:04d}.jpg"), type="jpeg", quality=92)
            b.close()
        # 3. music underneath the voice (ducked)
        music = synth(story["app"], 7, total) * 0.28
        n = min(len(vo), len(music))
        mix = np.clip(vo[:n] + music[:n], -0.98, 0.98)
        audio = tmp / "mix.m4a"; write_m4a(mix, audio)
        out = out_dir / f"{story['id']}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "f%04d.jpg"), "-i", str(audio),
                        "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
                        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], check=True)
        print(f"{out} {total:.1f}s")
        return out


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
