import subprocess
from playwright.sync_api import sync_playwright
BASE="http://localhost:8092"
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":390,"height":844}, device_scale_factor=3, is_mobile=True, has_touch=True)
    pg=ctx.new_page(); shots=[]
    for i,(r) in enumerate(["/", "/onboarding", "/(tabs)", "/daily-path", "/create", "/explore"]):
        try:
            pg.goto(BASE+r, wait_until="networkidle", timeout=60000); pg.wait_for_timeout(3000)
            f=f"s{i}.png"; pg.screenshot(path=f); shots.append(f); print(r,"->",pg.url.replace(BASE,""))
        except Exception as e: print(r,"ERR",str(e)[:60])
    b.close()
ins=sum([["-i",f] for f in shots],[])
fl="".join(f"[{i}:v]scale=200:-1[v{i}];" for i in range(len(shots)))+"".join(f"[v{i}]" for i in range(len(shots)))+f"hstack={len(shots)}"
subprocess.run(["ffmpeg","-y","-loglevel","error",*ins,"-filter_complex",fl,"sheet.png"],check=True)
