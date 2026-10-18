"""Render Play Store assets: framed screenshots (1080x1920) and a feature graphic (1024x500).

python3 render_store.py <app> <shots_dir> <plan.json> [out folder name, default the app name]
plan.json: {"screens":[{"file":"s2.png","h1":"...","sub":"..."}], "feature":{"shot":"s2.png","h1":"...","sub":"..."}}
"""
import json, sys, urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parent
APPS = json.loads((ROOT.parent / "content" / "apps.json").read_text())

def main(app, shots_dir, plan_path, out_name=None):
    cfg = APPS[app]; plan = json.loads(Path(plan_path).read_text())
    out = ROOT / "out" / (out_name or app); out.mkdir(parents=True, exist_ok=True)
    icon = (ROOT.parent / cfg["icon"]).resolve().as_uri()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1080, "height": 1920})
        for i, s in enumerate(plan["screens"], 1):
            params = {"palette": cfg["palette"], "h1": s["h1"], "sub": s.get("sub", ""),
                      "shot": (Path(shots_dir) / s["file"]).resolve().as_uri()}
            pg.goto((ROOT / "templates" / "frame.html").as_uri() + "?p=" + urllib.parse.quote(json.dumps(params)))
            pg.evaluate("document.fonts.ready"); pg.wait_for_function("[...document.images].every(i=>i.complete)")
            pg.wait_for_timeout(200); pg.screenshot(path=str(out / f"screenshot_{i}.png"))
        f = plan["feature"]
        pg2 = b.new_page(viewport={"width": 1024, "height": 500})
        params = {"palette": cfg["palette"], "name": cfg["name"], "icon": icon, "h1": f["h1"], "sub": f.get("sub", ""),
                  "shot": (Path(shots_dir) / f["shot"]).resolve().as_uri()}
        pg2.goto((ROOT / "templates" / "feature.html").as_uri() + "?p=" + urllib.parse.quote(json.dumps(params)))
        pg2.evaluate("document.fonts.ready"); pg2.wait_for_function("[...document.images].every(i=>i.complete)")
        pg2.wait_for_timeout(200); pg2.screenshot(path=str(out / "feature_graphic.png"))
        b.close()
    print("wrote", len(plan["screens"]), "screenshots + feature graphic to", out)

if __name__ == "__main__":
    main(*sys.argv[1:5])
