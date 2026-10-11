import json, subprocess, urllib.request
from playwright.sync_api import sync_playwright
BASE="http://localhost:8091"; LOCAL="http://localhost:9999/.netlify/functions/"
SESSION={"phone":"","sessionToken":"","name":"Ramesh","businessName":"Sharma General Store","businessType":"Retail / Shop","plan":"starter","founder":True,"isAdmin":False,"country":{"code":"IN"}}
PLAN={"plan":"trial","businessName":"Sharma General Store","phone":"9876543210","registeredAt":"2026-10-01T00:00:00Z","planExpiresAt":None,"planLabel":None,"aiIncluded":True,"planEndsAt":None,"actor":"owner","staffName":None,"staffId":None,"shop":None,"shops":1,"country":{"code":"IN","name":"India","currency":"INR","symbol":"₹"},"hasAccess":True,"trialDays":30,"trialDaysLeft":21}
ROUTES=["dashboard"]
def handle(route, req):
    fn=req.url.split("/functions/")[1].split("?")[0]
    if fn=="check-plan":
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin":"*"}, body=json.dumps(PLAN))
    try:
        r=urllib.request.Request(LOCAL+fn, data=req.post_data_buffer or b"{}", method="POST", headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(r, timeout=60) as resp:
            body=resp.read(); status=resp.status
    except urllib.error.HTTPError as e:
        body=e.read(); status=e.code
    route.fulfill(status=status, content_type="application/json", headers={"Access-Control-Allow-Origin":"*"}, body=body)
seen={}
with sync_playwright() as p:
    b=p.chromium.launch()
    ctx=b.new_context(viewport={"width":390,"height":844}, device_scale_factor=3, is_mobile=True, has_touch=True, locale="en-IN", timezone_id="Asia/Kolkata", geolocation={"latitude":28.61,"longitude":77.2}, permissions=["geolocation"])
    ctx.add_init_script("try{localStorage.setItem('smb_session', %s); localStorage.setItem('smb_country','IN'); localStorage.setItem('smb_country_ip','IN'); localStorage.setItem('smb_lang','en');}catch(e){}" % json.dumps(json.dumps(SESSION)))
    ctx.route("https://scoremybiz.com/.netlify/functions/**", lambda route, req: (seen.setdefault(req.url.split('/functions/')[1],0), handle(route, req)))
    pg=ctx.new_page()
    for r in ROUTES:
        try:
            pg.goto(f"{BASE}/{r}", wait_until="networkidle", timeout=60000); pg.wait_for_timeout(4000)
            pg.screenshot(path=f"{r}.png"); print(r,"ok")
        except Exception as e: print(r,"ERR",str(e)[:70])
    b.close()
print("functions called:", sorted(seen))
files=[f"{r}.png" for r in ROUTES]
ins=sum([["-i",f] for f in files],[])
fl="".join(f"[{i}:v]scale=200:-1[v{i}];" for i in range(len(files)))+"".join(f"[v{i}]" for i in range(len(files)))+f"hstack={len(files)}"
subprocess.run(["ffmpeg","-y","-loglevel","error",*ins,"-filter_complex",fl,"sheet.png"],check=True)
