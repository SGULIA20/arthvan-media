"""Character story ads: voice (macOS say) + animated SVG scenes (Playwright) + music + subtitles → MP4.

python -m engine.story stories/lumi_friday_hi.json out_dir
"""
import json, subprocess, sys, tempfile, wave
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

from .config import ROOT, load_apps
from .music import synth, write_m4a

TEMPLATE = ROOT / "engine" / "templates" / "story.html"
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
            d = voice_clip(s["vo"], story["voice"], story.get("rate", 175), wav)
            s["dur"] = round(max(s.get("min", 4), d + 1.2), 2)
            clips.append((wav, d))
        total = sum(s["dur"] for s in story["scenes"])
        # 2. frames
        deck = {"scenes": story["scenes"], "title": story["title"], "end_line": app["end_line"],
                "disclaimer": app.get("money_disclaimer") or "", "icon": (ROOT / app["icon"]).as_uri(),
                "badge": BADGE.as_uri(), "shots": (ROOT / "store" / "shots" / story["app"]).as_uri()}
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
        # 3. voice track laid on the timeline, music underneath (ducked)
        sr = 44100
        vo = np.zeros((int(total * sr) + sr, 2), dtype=np.float32)
        t0 = 0.0
        for s, (wav, d) in zip(story["scenes"], clips):
            with wave.open(str(wav)) as w:
                a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32).reshape(-1, 2) / 32768
            start = int((t0 + 0.4) * sr); vo[start:start + len(a)] += a * 0.95; t0 += s["dur"]
        vo = vo[: int(total * sr)]
        music = synth(story["app"], 7, total) * 0.28
        mix = np.clip(vo + music, -0.98, 0.98)
        audio = tmp / "mix.m4a"; write_m4a(mix, audio)
        out = out_dir / f"{story['id']}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(frames / "f%04d.jpg"), "-i", str(audio),
                        "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
                        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], check=True)
        print(f"{out} {total:.1f}s")
        return out


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
