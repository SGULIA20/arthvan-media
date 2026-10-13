"""Turn the newest snapshot (and the previous one) into a themes report: rules for the counts, and, when a
GEMINI_API_KEY is available, three story ideas per app in our characters' voices (ideas, never copies).
python -m radar.report            prints Markdown; writes radar/reports/YYYY-MM-DD.md
"""
import json, re, sys
from collections import Counter
from pathlib import Path

from engine.gemini import GeminiError, ask
from engine.tts import api_key
from engine.broll import status_line
from engine.coverage import summary_line as coverage_line

HERE = Path(__file__).resolve().parent
THEMES = {
 "scoremybiz": {
  "collect dues / udhar": r"\budhar\b|\bdues?\b|\bcollect|\breminder|\bkhata\b|\bbaki\b|\bpayment reminder",
  "GST and bills": r"\bgst\b|\binvoice|\bbills?\b|\bbilling\b|\be-?way\b|\be-?invoice",
  "cash and profit visibility": r"\bcash\b|\bprofit|\bloss\b|\bbalance\b|\bcash ?flow",
  "stock and inventory": r"\bstock\b|\binventory",
  "free / trial / price": r"\bfree\b|\btrial\b|\bno credit card|\bpaid\b|\bsubscription",
  "WhatsApp and sharing": r"\bwhatsapp\b|\bshare\b",
  "offline and simple": r"\boffline\b|\bsimple\b|\beasy\b|\bno accountant",
  "festival season": r"\bdiwali\b|\bfestival|\bnavratri|\bdussehra|\bseason",
  "security / backup": r"\bsecure|\bbackup|\bsafe\b|\bdata\b"},
 "waypoint": {
  "anonymous / no identity": r"\banonym|\bsecret|\bno name|\bidentity",
  "say what you can't": r"\bconfess|\bhonest|\bsay (it|what|anything)|\bvent\b|\bshare your",
  "questions and prompts": r"\bquestion|\bask me|\bq&a|\bprompt",
  "calm / sleep / stress": r"\bcalm\b|\bsleep\b|\bstress|\bmeditat|\banxi|\bbreath",
  "meet people / chat": r"\bchat\b|\bmeet\b|\bstranger|\btalk to|\bconversation|\bfriends?\b",
  "community / belonging": r"\bcommunity|\btogether|\bnot alone|\bbelong",
  "free / premium": r"\bfree\b|\bpremium\b|\bsubscri",
  "safety / moderation": r"\bsafe\b|\bmoderat|\breport\b|\bblock\b"},
}


def texts(row: dict) -> str:
    p = row.get("play") or {}
    return " ".join(filter(None, [p.get("title"), p.get("short"), p.get("about")] + [v["title"] for v in row.get("youtube", [])])).lower()


def score(app: str, row: dict) -> Counter:
    t = texts(row)
    return Counter({name: len(re.findall(rx, t)) for name, rx in THEMES[app].items()})


CHARACTERS = {"scoremybiz": "Lumi (a warm, practical guide for Indian shopkeepers) and the founder character (a calm man in a suit)",
              "waypoint": "Mira (a gentle young woman) and the founder character (a casual young man)"}
FEATURES = {
 "scoremybiz": "Real screens only: Dashboard (today's Sold, Bought, Spent, money in hand, who owes you with one-tap reminders); "
               "Book (daily entries); Profit & Loss (plain words); Cash reality (profit on paper vs cash in hand); "
               "Score history (one number out of 100 for the shop's health, seven areas); Advisor (three moves for the week); Tasks.",
 "waypoint": "Real screens only: Create (one true sentence under a new name you get each day); Daily Path (one question, the same for everyone); "
             "Wall (tonight's sentences from others); Matching (cross paths with one person for a short conversation); Calm kit (breathe, ground, wind down); Explore.",
}
RULES = ("Rules: give three ideas, each in two or three lines: title, the person and their moment, which app screen we show. "
         "Use the competitors only for the IDEA behind their message; never copy their words, scenes or metaphors "
         "(for example, no doctor or check-up metaphor if a competitor used one). Plain shopkeeper words for ScoreMyBiz: "
         "Sold, Bought, Spent; never accountant terms. No claims about privacy, safety, mental health or numbers. "
         "No 'I built this' lines. Answer in Markdown as a numbered list, nothing else.")


def ideas_prompt(app: str, comps: dict) -> str:
    lines = [f"- {name}: {texts(row)[:400]}" for name, row in comps.items()]
    return (f"You write 45-second story ads for the app {app}, told by {CHARACTERS.get(app, 'our characters')}. "
            f"This week's competitor listings and video titles:\n" + "\n".join(lines) + "\n\n"
            f"{FEATURES.get(app, '')} Invent no other feature or screen.\n\n" + RULES)


def render(cur: dict, prev, gemini: bool) -> str:
    out = [f"# Ad radar — week to {cur['date']}", ""]
    for app, comps in cur["apps"].items():
        total = Counter(); per = {}
        for name, row in comps.items():
            sc = score(app, row); per[name] = sc; total.update(sc)
        out += [f"## {app}", "", "| Theme | Mentions this week | Who pushes it most |", "|---|---|---|"]
        for theme, n in total.most_common():
            if n == 0: continue
            top = max(per, key=lambda k: per[k][theme])
            out.append(f"| {theme} | {n} | {top} ({per[top][theme]}) |")
        out += ["", "**Newest videos found:**"]
        for name, row in comps.items():
            for v in row.get("youtube", [])[:2]:
                out.append(f"- {name}: [{v['title']}](https://www.youtube.com/watch?v={v['id']})")
        if prev and app in prev["apps"]:
            moves = []
            for name, row in comps.items():
                p0 = (prev["apps"][app].get(name) or {}).get("play") or {}; p1 = row.get("play") or {}
                if p0.get("short") and p1.get("short") and p0["short"] != p1["short"]:
                    moves.append(f"- {name} changed its store tagline: “{p0['short'][:70]}” → “{p1['short'][:70]}”")
                new = [v for v in row.get("youtube", []) if v["id"] not in {x["id"] for x in (prev["apps"][app].get(name) or {}).get("youtube", [])}]
                if new: moves.append(f"- {name}: {len(new)} new video(s), e.g. “{new[0]['title'][:60]}”")
            out += ["", "**Changed since last week:**"] + (moves or ["- nothing"])
        top3 = [t for t, n in total.most_common(3) if n]
        out += ["", f"**Suggested themes for next week's {app} content:** " + ", ".join(top3), ""]
        if gemini:
            try:
                out += ["**Three story ideas (Gemini):**", "", ask(ideas_prompt(app, comps)), ""]
            except GeminiError as e:
                out += [f"_Story ideas skipped: {e}_", ""]
    out += ["", status_line(), coverage_line(), ""]
    return "\n".join(out)


def main() -> int:
    snaps = sorted((HERE / "snapshots").glob("*.json"))
    if not snaps:
        print("no snapshots"); return 1
    cur = json.loads(snaps[-1].read_text())
    prev = json.loads(snaps[-2].read_text()) if len(snaps) > 1 else None
    md = render(cur, prev, gemini=bool(api_key()))
    (HERE / "reports").mkdir(exist_ok=True); (HERE / "reports" / f"{cur['date']}.md").write_text(md)
    print(md); return 0


if __name__ == "__main__":
    sys.exit(main())
