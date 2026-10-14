"""Real screens of the ScoreMyBiz CA portal (app routes ca-portfolio, ca-card, ca-profile, ca-client) with the SERVER'S OWN SAMPLE DATA
(lib/agent-auth.js FOUNDER_SAMPLE_AGENT: 'CA Priya Mehta', six sample clients): no real account, no database.
Needs: app web on :8091 (EXPO_PUBLIC_FOUNDER_KEY=sg2026 npx expo start --web --port 8091) and
       functions on :9999 (FOUNDER_KEY=sg2026 SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_ROLE_KEY=dummy netlify functions:serve --port 9999).
python store/capture_ca.py <outdir> [route,list]"""
import json
import sys
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
ROUTES = sys.argv[2].split(",") if len(sys.argv) > 2 else ["ca-portfolio", "ca-card", "ca-profile"]
BASE, LOCAL, KEY = "http://localhost:8091", "http://localhost:9999/.netlify/functions/", "sg2026"
CA_SESSION = {"phone": "919999999999", "agentSessionToken": "sample", "name": "CA Priya Mehta",
              "firmName": "Mehta & Associates, Chartered Accountants", "agentType": "ca"}


CLEAN_JS = r"""() => {   // remove the dev-build warning bubble and any "Founder test mode" notice, with the box that holds only that text
  const pat = /cannot contain a nest|Founder test mode|This is sample mode|Sample mode|Unhandled|Warning:/i;
  const norm = s => (s || '').replace(/\s+/g, '');
  const hits = [...document.querySelectorAll('*')].filter(e => pat.test(e.innerText || '') && (e.innerText || '').length < 1500 && ![...e.children].some(c => pat.test(c.innerText || '')));
  hits.forEach(e => { let n = e; while (n.parentElement && n.parentElement !== document.body && norm(n.parentElement.innerText) === norm(n.innerText)) n = n.parentElement; n.remove(); });
}"""


def handle(route, req):
    fn = req.url.split("/functions/")[1].split("?")[0]
    try:
        body = json.loads(req.post_data or "{}")
    except ValueError:
        body = {}
    body["founderKey"] = KEY                                   # the server then answers as its sample CA
    try:
        r = urllib.request.Request(LOCAL + fn, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=60) as resp:
            data, status = resp.read(), resp.status
    except urllib.error.HTTPError as e:
        data, status = e.read(), e.code
    route.fulfill(status=status, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=data)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True, locale="en-IN", timezone_id="Asia/Kolkata")
    ctx.add_init_script("try{localStorage.setItem('smb_ca_session', %s); localStorage.setItem('smb_lang','en'); localStorage.setItem('smb_country','IN');}catch(e){}" % json.dumps(json.dumps(CA_SESSION)))
    ctx.route("https://scoremybiz.com/.netlify/functions/**", handle)
    pg = ctx.new_page()
    for r in ROUTES:
        try:
            pg.goto(f"{BASE}/{r}", wait_until="networkidle", timeout=120000); pg.wait_for_timeout(5000)
            pg.evaluate(CLEAN_JS)
            toast = pg.locator("text=/cannot contain a nest/")           # Playwright's text engine also reaches inside shadow DOM, where the dev bubble may live
            for k in range(toast.count()):
                toast.nth(k).evaluate("e => { let n = e; for (let i = 0; i < 5 && n.parentElement; i++) { n = n.parentElement; if (getComputedStyle(n).position === 'fixed' || getComputedStyle(n).position === 'absolute') break; } n.style.display = 'none'; }")
            pg.wait_for_timeout(500)
            pg.screenshot(path=f"{OUT}/{r}.png"); print(r, "ok")
        except Exception as e:
            print(r, "ERR", str(e)[:90])
    b.close()
