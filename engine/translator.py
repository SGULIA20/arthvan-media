"""Automatic translation of Reel scripts with Gemini, for the daily production run. Output is DRAFT quality: every file it writes carries
"machine_translated": true until a native speaker has read it. A translation that fails the checks below is rejected, never rendered.
(Hindi was written by hand; its files have no such flag.)"""
import json
import re
import unicodedata
from pathlib import Path

from . import gemini
from .library import LANGUAGES

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAMES = {"hi": "ScoreMyBiz = स्कोर माय बिज़, Waypoint = वेपॉइंट"}        # how a non-Latin language should spell the brand so the voice says it right

PROMPT = """You translate the script of a short Instagram Reel ad into {language}. A text-to-speech voice reads each line aloud and the same words are the subtitles.
Rules:
- Say it the way a friendly shopkeeper-level speaker of {language} would say it: everyday words, short sentences, no formal or bookish wording.
  Use the standard spoken form that people across the whole region understand, not slang and not one city's or caste's dialect.
- Keep the meaning, the number of lines and every number exactly. Do not add or remove any claim, promise or warning.
- Names of people: keep them recognisable (use {language}'s own script if it has one). Product names ScoreMyBiz, Waypoint, WhatsApp, QuickBooks, Xero, Wave, CA: if {language} does not use Latin letters, write how they sound in that script; otherwise keep them as they are.
- Each translated line should be about as long as the English line, at most 20% longer{strict}.
- A line may carry a short on-screen "card": translate it too.
Return ONLY valid JSON of exactly this shape, nothing else:
{{"title": "...", "caption": "...", "scenes": [{{"vo": "...", "card": "... (only if the input has a card)"}}]}}
Input:
{payload}"""

END_PROMPT = """Translate these four short texts for the end card of a mobile-app ad into {language}. Keep them short and natural. {{n}} stays exactly as {{n}}.
Return ONLY valid JSON: {{"end_line": "...", "link_in_bio": "...", "languages_phrase": "...", "money_disclaimer": "..."}}
Input: {payload}"""


class TranslationRejected(Exception):
    pass


def _json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def _numbers(s: str) -> set:
    out = set()
    for tok in re.findall(r"\d+", s):                                  # \d also matches other scripts' digits; int() normalises them
        out.add(int(tok))
    return out


def problems(base: dict, tr: dict) -> list:
    out = []
    scenes = tr.get("scenes") or []
    if len(scenes) != len(base["scenes"]):
        return [f"{len(scenes)} scenes, expected {len(base['scenes'])}"]
    for i, (b, t) in enumerate(zip(base["scenes"], scenes)):
        vo = (t.get("vo") or "").strip()
        if not vo:
            out.append(f"scene {i}: empty line"); continue
        ratio = len(vo) / max(1, len(b.get("vo", "")))
        if not 0.35 <= ratio <= 2.4:
            out.append(f"scene {i}: length {ratio:.1f}x the English")
        if _numbers(b.get("vo", "")) and not _numbers(b["vo"]) <= _numbers(vo):
            out.append(f"scene {i}: numbers changed")
        if b.get("card") and not (t.get("card") or "").strip():
            out.append(f"scene {i}: card missing")
    if not (tr.get("caption") or "").strip() or not (tr.get("title") or "").strip():
        out.append("title or caption missing")
    return out


def translate_story(base: dict, lang: str, ask=gemini.ask, strict: bool = False) -> dict:
    name = LANGUAGES.get(lang, lang)
    payload = json.dumps({"title": base.get("title", ""), "caption": base.get("caption", ""),
                          "scenes": [({"vo": s.get("vo", "")} | ({"card": s["card"]} if s.get("card") else {})) for s in base["scenes"]]}, ensure_ascii=False)
    prompt = PROMPT.format(language=name, payload=payload, strict=" and shorter if you can (this Reel must stay under 60 seconds)" if strict else "")
    last = []
    for _ in range(2):
        tr = _json(ask(prompt, max_tokens=4000))
        last = problems(base, tr)
        if not last:
            tr["machine_translated"] = True
            return tr
    raise TranslationRejected(f"{base['id']} -> {lang}: {'; '.join(last)}")


def translate_end_card(app_cfg: dict, lang: str, ask=gemini.ask) -> dict:
    src = {k: app_cfg.get(k, "") for k in ("end_line", "link_in_bio", "languages_phrase", "money_disclaimer")}
    src["link_in_bio"] = src["link_in_bio"] or "Link in bio"
    src = {k: v for k, v in src.items() if v}
    out = _json(ask(END_PROMPT.format(language=LANGUAGES.get(lang, lang), payload=json.dumps(src, ensure_ascii=False)), max_tokens=800))
    if "{n}" not in out.get("languages_phrase", ""):
        raise TranslationRejected(f"end card for {lang}: languages phrase lost its {{n}}")
    return {k: v for k, v in out.items() if k in src and str(v).strip()}


def ensure_files(base_story: dict, app_key: str, app_cfg: dict, lang: str, root: Path = ROOT, ask=gemini.ask, strict: bool = False) -> Path:
    """Write content/translations/<lang>/<id>.json (and the language's end card texts once). Returns the translation path."""
    root = Path(root)
    card = root / "content" / "end_card" / f"{lang}.json"
    have = json.loads(card.read_text()) if card.exists() else {}
    if app_key not in have and lang not in (app_cfg.get("i18n") or {}):
        have[app_key] = translate_end_card(app_cfg, lang, ask)
        card.parent.mkdir(parents=True, exist_ok=True); card.write_text(json.dumps(have, indent=1, ensure_ascii=False) + "\n")
    path = root / "content" / "translations" / lang / f"{base_story['id']}.json"
    if not path.exists() or strict:
        path.parent.mkdir(parents=True, exist_ok=True)
        tr = translate_story(base_story, lang, ask, strict)
        end = base_story["scenes"][-1]                                  # the closing line is the standard one for the app, said in the language
        path.write_text(json.dumps(tr, indent=1, ensure_ascii=False) + "\n")
    return path
