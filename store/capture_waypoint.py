"""Capture Waypoint screens from the web build (npx expo start --web --port 8092 in ~/waypoint).
python3 capture_waypoint.py <outdir>"""
import subprocess, sys
from playwright.sync_api import sync_playwright
BASE="http://localhost:8092"; OUT=sys.argv[1] if len(sys.argv)>1 else "."
def shot(pg, path, name):
    pg.goto(BASE+path, wait_until="networkidle", timeout=60000); pg.wait_for_timeout(2500); pg.screenshot(path=f"{OUT}/{name}.png"); print(name,"ok")
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":390,"height":844}, device_scale_factor=3, is_mobile=True, has_touch=True)
    pg=ctx.new_page()
    shot(pg,"/","welcome")
    shot(pg,"/(tabs)","wall")
    shot(pg,"/daily-path","daily-path")
    shot(pg,"/calm","calm")
    shot(pg,"/matching","matching")
    shot(pg,"/explore","explore")
    pg.goto(BASE+"/create", wait_until="networkidle", timeout=60000); pg.wait_for_timeout(2000)
    try:
        box=pg.locator("textarea").first; box.click(); box.fill("I am fine all day. At night I am not. I have never said that to anyone.")
        pg.wait_for_timeout(600); pg.screenshot(path=f"{OUT}/create_typed.png"); print("create_typed ok")
    except Exception as e: print("create_typed ERR", str(e)[:80])
    b.close()
