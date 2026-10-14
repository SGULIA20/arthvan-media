"""Waypoint screens that need a little server data, captured with SAMPLE values (no real account): the invite code card on My Waypoints
(sample code), the Talk to Mira button on the Chats tab and on the matching screen (after its wait). Needs the Waypoint web build on :8092.
python store/capture_waypoint_more.py <outdir> [lang]"""
import json
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8092"
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
LANG = sys.argv[2] if len(sys.argv) > 2 else "en"
SAMPLE_CODE = "WAYP7K2M"


def rpc(route, req):
    url = req.url
    if "get_my_invite_code" in url:
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(SAMPLE_CODE))
    if "get_my_invite_count" in url:
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body="1")
    route.continue_()


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True)
    ctx.add_init_script("try{localStorage.setItem('appLanguage','%s');}catch(e){}" % LANG)
    ctx.route("**/rest/v1/rpc/**", rpc)
    pg = ctx.new_page()
    try:                                                   # 1) invite code card
        pg.goto(BASE + "/my-waypoints", wait_until="networkidle", timeout=90000); pg.wait_for_timeout(4000)
        card = pg.get_by_text(SAMPLE_CODE)
        if card.count():
            card.first.scroll_into_view_if_needed(); pg.evaluate("window.scrollBy(0, -260)"); pg.wait_for_timeout(600)
            pg.screenshot(path=f"{OUT}/invite.png"); print("invite ok")
        else:
            print("invite: code card not shown (userId missing?)")
    except Exception as e:
        print("invite ERR", str(e)[:90])
    try:                                                   # 2) chats tab with Talk to Mira
        pg.goto(BASE + "/chats", wait_until="networkidle", timeout=90000); pg.wait_for_timeout(5000)
        pg.screenshot(path=f"{OUT}/chats.png"); print("chats ok")
    except Exception as e:
        print("chats ERR", str(e)[:90])
    try:                                                   # 3) matching screen once the Mira button has appeared
        pg.goto(BASE + "/matching", wait_until="networkidle", timeout=90000)
        pg.get_by_text("Talk to Mira while you wait").wait_for(timeout=90000); pg.wait_for_timeout(800)
        pg.screenshot(path=f"{OUT}/matching-mira.png"); print("matching-mira ok")
    except Exception as e:
        print("matching-mira ERR", str(e)[:90])
    b.close()
