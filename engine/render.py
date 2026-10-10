"""Render a selected item into post slides (4:5 JPEG) and a Reel/Story video (9:16 MP4 with music)."""
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

from .config import ROOT
from .music import synth, write_m4a
from .select_item import Selection

TEMPLATE = ROOT / "engine" / "templates" / "deck.html"
BADGE = ROOT / "engine" / "assets" / "google-play-badge.png"
SIZES = {"post": (1080, 1350), "reel": (1080, 1920)}
MIN_STD = 12.0


@dataclass
class RenderedSet:
    slides: list
    reel: Path
    story: Path
    seconds: float


def _deck(sel: Selection, app_cfg: dict) -> dict:
    has_sample = any(s.get("sample") for s in sel.item["slides"])
    return {
        "app": {k: app_cfg[k] for k in ("name", "palette", "end_line")},
        "item": sel.item,
        "disclaimer": app_cfg.get("money_disclaimer") if has_sample else None,
        "assets": {"icon": (ROOT / app_cfg["icon"]).as_uri(), "badge": BADGE.as_uri()},
    }


def _open(browser, deck: dict, fmt: str):
    w, h = SIZES[fmt]
    page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
    page.add_init_script(f"window.DECK={json.dumps(deck)};window.FORMAT={json.dumps(fmt)};")
    page.goto(TEMPLATE.as_uri())
    page.evaluate("document.fonts.ready")
    page.wait_for_function("[...document.images].every(i => i.complete)")
    page.wait_for_timeout(250)
    return page


def render_set(sel: Selection, app_cfg: dict, out_dir: Path, fps: int = 30) -> RenderedSet:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    deck = _deck(sel, app_cfg)
    slides, reel = [], out_dir / "reel.mp4"
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        browser = p.chromium.launch()
        post = _open(browser, deck, "post")
        for i in range(post.evaluate("SLIDE_COUNT")):
            post.evaluate(f"render(settleTime({i}), true)")
            png = tmp / f"s{i}.png"
            post.screenshot(path=str(png))
            jpg = out_dir / f"slide_{i + 1}.jpg"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), "-q:v", "2",
                            "-pix_fmt", "yuvj420p", str(jpg)], check=True)
            slides.append(jpg)
        page = _open(browser, deck, "reel")
        total = float(page.evaluate("TOTAL"))
        frames = tmp / "frames"
        frames.mkdir()
        for f in range(int(round(total * fps))):
            page.evaluate(f"render({f / fps})")
            page.screenshot(path=str(frames / f"f{f:04d}.jpg"), type="jpeg", quality=92)
        browser.close()
        music = tmp / "music.m4a"
        write_m4a(synth(sel.app, sel.day.toordinal() + sel.bank_index, total), music)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(frames / "f%04d.jpg"),
                        "-i", str(music), "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                        "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "160k",
                        "-movflags", "+faststart", str(reel)], check=True)
    return RenderedSet(slides=slides, reel=reel, story=reel, seconds=total)


def _gray(args: list, w: int, h: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", *args, "-frames:v", "1", "-vf", f"scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8)


def _probe(path: Path, entries: str) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "default=nw=1", str(path)],
                          capture_output=True, text=True, check=True).stdout


def verify_image(path: Path, w: int, h: int) -> list:
    probe = _probe(path, "stream=width,height")
    got = (int(re.search(r"width=(\d+)", probe).group(1)), int(re.search(r"height=(\d+)", probe).group(1)))
    problems = []
    if got != (w, h):
        problems.append(f"{path.name}: size {got}, expected {(w, h)}")
    if _gray(["-i", str(path)], got[0], got[1]).std() < MIN_STD:
        problems.append(f"{path.name}: looks blank")
    return problems


def verify_set(rs: RenderedSet) -> list:
    problems = []
    for s in rs.slides:
        problems += verify_image(s, 1080, 1350)
    probe = _probe(rs.reel, "stream=codec_name,codec_type,width,height:format=duration")
    if "codec_name=h264" not in probe or "width=1080" not in probe or "height=1920" not in probe:
        problems.append("reel is not 1080x1920 h264")
    if "codec_type=audio" not in probe:
        problems.append("reel has no audio stream")
    dur = float(re.search(r"duration=([\d.]+)", probe).group(1))
    if not 15.0 <= dur <= 30.0:
        problems.append(f"reel duration {dur:.1f}s outside 15 to 30")
    for t in (1.0, dur / 2, dur - 0.6):
        if _gray(["-ss", f"{t:.2f}", "-i", str(rs.reel)], 1080, 1920).std() < MIN_STD:
            problems.append(f"reel frame at {t:.1f}s looks blank")
    vol = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(rs.reel), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", vol)
    if not m or float(m.group(1)) < -45:
        problems.append("reel audio is silent")
    return problems
