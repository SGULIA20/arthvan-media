"""More Waypoint screens for feature-led Reels (web build on port 8092 in ~/waypoint). Only screens that need no real
user content: polls and voice on Create, Break Room, My Waypoints, Wrapped, Reveal, language picker, Saved, Customize.
python3 capture_waypoint_features.py <outdir>"""
import sys
from playwright.sync_api import sync_playwright
BASE = "http://localhost:8092"; OUT = sys.argv[1] if len(sys.argv) > 1 else "."
ONLY = sys.argv[3].split(",") if len(sys.argv) > 3 else None          # e.g. reveal,customize (poll and voice only when named)
LANGUAGE = sys.argv[2] if len(sys.argv) > 2 else "en"      # app language code, e.g. hi, es, sw, pt, bn, ta
ROUTES = {"break-room": "/break-room", "my-waypoints": "/my-waypoints", "wrapped": "/wrapped", "reveal": "/reveal", "language": "/language",
          "saved": "/saved", "customize": "/customize", "how-it-works": "/how-it-works", "whats-new": "/whats-new"}


def go(pg, path, wait=2500):
    pg.goto(BASE + path, wait_until="networkidle", timeout=60000); pg.wait_for_timeout(wait)


with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True)
    ctx.add_init_script("try{localStorage.setItem('appLanguage','%s');}catch(e){}" % LANGUAGE)
    pg = ctx.new_page()
    for name, path in ROUTES.items():
        if ONLY and name not in ONLY:
            continue
        try:
            go(pg, path); pg.screenshot(path=f"{OUT}/{name}.png"); print(name, "ok")
        except Exception as e:
            print(name, "ERR", str(e)[:80])
    for name, label, fill in (("poll", "Ask the Path", True), ("voice", "Voice", False)):
        if not ONLY or name not in ONLY:
            continue
        try:
            go(pg, "/create", 2000)
            pg.get_by_text(label, exact=False).first.click(); pg.wait_for_timeout(1000)
            if fill:
                boxes = pg.locator("input, textarea")
                texts = ["New city, or stay close to home?", "New city", "Stay close to home"]
                for i, t in enumerate(texts[: boxes.count()]):
                    try: boxes.nth(i).fill(t)
                    except Exception: pass
                pg.wait_for_timeout(600)
            pg.screenshot(path=f"{OUT}/{name}.png"); print(name, "ok")
        except Exception as e:
            print(name, "ERR", str(e)[:80])
    b.close()
