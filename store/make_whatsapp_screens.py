"""Two WhatsApp chat pictures for the ScoreMyBiz bot Reel, using the bot's REAL wording (netlify/functions/lib/whatsapp-menu.js menuText for
India, and the 'Recorded. ...' reply in whatsapp-webhook.js). Output: store/shots/scoremybiz/en/whatsapp-menu.png and whatsapp-numbers.png (1170x2532).
python store/make_whatsapp_screens.py"""
import html
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "shots" / "scoremybiz" / "en"
EXAMPLE = "sales 5000 expenses 1200 cash 3000"
MENU = ["Namaste Ravi! What would you like today? Reply with a number:", "1. My score and numbers", "2. Profit and loss", "3. Who owes me money",
        f'4. Add today\'s sales (type: "{EXAMPLE}")', "5. Renew my plan", "6. Report a problem", "7. Ask the Advisor a question",
        "Or send a photo of your notebook, or a voice note."]

CSS = """
*{box-sizing:border-box;margin:0}
body{width:390px;height:844px;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;background:#ECE5DD;display:flex;flex-direction:column;overflow:hidden}
.top{background:#075E54;color:#fff;padding:14px 12px 12px;display:flex;align-items:center;gap:10px}
.back{font-size:26px;line-height:1;margin-right:2px}
.av{width:38px;height:38px;border-radius:50%;background:#001B4D;border:2px solid #F2A93B;color:#F2A93B;font-weight:800;font-size:13px;display:flex;align-items:center;justify-content:center}
.nm{font-size:18px;font-weight:600}.sub{font-size:12.5px;opacity:.8;margin-top:1px}
.chat{flex:1;padding:14px 10px;display:flex;flex-direction:column;gap:7px;justify-content:flex-end}
.day{align-self:center;background:#E1F3FB;color:#54656F;font-size:12px;padding:4px 10px;border-radius:7px;margin:4px 0}
.b{max-width:84%;padding:8px 10px 6px;border-radius:9px;font-size:16px;line-height:1.32;color:#111;box-shadow:0 1px .5px rgba(0,0,0,.13);white-space:pre-line}
.me{align-self:flex-end;background:#D9FDD3;border-top-right-radius:2px}
.bot{align-self:flex-start;background:#fff;border-top-left-radius:2px}
.t{display:block;text-align:right;font-size:11px;color:#667781;margin-top:3px}
.me .t::after{content:" ✓✓";color:#53BDEB}
.bar{background:#F0F2F5;padding:9px 10px;display:flex;gap:8px;align-items:center}
.in{flex:1;background:#fff;border-radius:22px;padding:11px 16px;color:#8696A0;font-size:16px}
.mic{width:44px;height:44px;border-radius:50%;background:#00A884;display:flex;align-items:center;justify-content:center;color:#fff;font-size:20px}
"""


def page(messages) -> str:
    body = "".join(f'<div class="day">{html.escape(m[1])}</div>' if m[0] == "day" else
                   f'<div class="b {m[0]}">{html.escape(m[1])}<span class="t">{m[2]}</span></div>' for m in messages)
    return (f"<!doctype html><meta charset=utf-8><style>{CSS}</style><body><div class=top><span class=back>‹</span><div class=av>SMB</div>"
            f"<div><div class=nm>ScoreMyBiz</div><div class=sub>Business account</div></div></div><div class=chat>{body}</div>"
            "<div class=bar><div class=in>Message</div><div class=mic>🎤</div></div>")


SCREENS = {
    "whatsapp-menu.png": [("day", "Today"), ("me", "hi", "9:41 PM"), ("bot", "\n".join(MENU), "9:41 PM")],
    "whatsapp-numbers.png": [("day", "Yesterday"), ("me", "sales 4200 expenses 900 cash 2600", "9:38 PM"),
                             ("bot", "Recorded. Sales ₹4200, expenses ₹900. Cash position ₹2600.", "9:38 PM"), ("day", "Today"),
                             ("me", EXAMPLE, "9:42 PM"), ("bot", "Recorded. Sales ₹5000, expenses ₹1200. Cash position ₹3000.", "9:42 PM")],
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=3)
        for name, msgs in SCREENS.items():
            pg.set_content(page(msgs)); pg.wait_for_timeout(200)
            pg.screenshot(path=str(OUT / name))
            print("wrote", OUT / name)
        b.close()


if __name__ == "__main__":
    main()
