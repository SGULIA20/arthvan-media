"""The same illustrated story in another language. The pictures carry no text, so a version costs only a translation (text) and a new voice (about Rs 4).
python -m engine.story_localize stories/mira_ekbaat_hi.json bn gu mr ta     writes stories/mira_ekbaat_bn.json ... (machine translated: flagged until a native reader has checked it)
Each version points at the original's pictures with "art_id", so nothing is drawn twice. Render it with: python -m engine.story stories/mira_ekbaat_bn.json stories/out"""
import copy
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import gemini, translator
from .library import LANGUAGES

ROOT = Path(__file__).resolve().parent.parent
# Live features used only as a label so the calendar may place the versions a few days apart (its "same feature within 10 days" rule is for feature demos, not for stories)
FEATURE_ROTATION = {"waypoint": ["reveal", "wall-feed", "mood-log", "saved-posts", "wrapped", "invite", "daily-path"],
                    "scoremybiz": ["whatsapp-daily-update", "score-history", "what-i-have-and-owe", "profit-on-paper-vs-cash", "next-moves", "business-card"]}
BANNER_PROMPT = """Translate this on-screen hook line of a short Instagram story Reel into {language}. It is shown at the top of the screen for the whole video, in two lines.
Keep the HTML tags (<em>...</em> highlights the key phrase, <br> is the line break) and the emoji exactly where they are, translate only the words between them.
Everyday spoken {language}, short. Use {language}'s own script. Return ONLY the translated line, nothing else.
Input: {banner}"""


def translate_banner(banner: str, lang: str, ask=gemini.ask) -> str:
    out = ask(BANNER_PROMPT.format(language=LANGUAGES.get(lang, lang), banner=banner), max_tokens=300).strip().strip('"').strip()
    if banner.count("<em>") != out.count("<em>") or banner.count("<br>") != out.count("<br>"):
        raise translator.TranslationRejected(f"banner: the tags changed: {out[:80]}")
    return out


def localize_story(base: dict, lang: str, ask=gemini.ask, order: int = 1) -> dict:
    """A copy of `base` in `lang`: voice and subtitles in that language's script, the banner, title and caption translated, the same pictures."""
    tr = translator.translate_story(base, lang, ask)
    st = copy.deepcopy(base)
    stem = base["id"].rsplit("-", 1)[0]
    st["id"], st["lang"], st["art_id"] = f"{stem}-{lang}", lang, base.get("art_id", base["id"])
    for sc, t in zip(st["scenes"], tr["scenes"]):
        sc["vo"] = t["vo"]
        if sc.get("layout") != "end":
            sc["sub"] = t["vo"]
        if t.get("card"):
            sc["card"] = t["card"]
    st["title"], st["caption"] = tr["title"], tr["caption"]
    if base.get("banner"):
        st["banner"] = translate_banner(base["banner"], lang, ask)
    rot = [f for f in FEATURE_ROTATION.get(base["app"], []) if f != base.get("feature")]
    if rot:
        st["feature"] = rot[(order - 1) % len(rot)]
    if base.get("post_on"):
        st["post_on"] = (date.fromisoformat(base["post_on"]) + timedelta(days=4 * order)).isoformat()
    st["machine_translated"] = True
    return st


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]); base = json.loads(path.read_text())
    for i, lang in enumerate(args[1:], 1):
        try:
            st = localize_story(base, lang, order=i)
        except Exception as e:
            print(f"{lang}: not made: {str(e)[:160]}"); continue
        out = path.with_name(path.name.rsplit("_", 1)[0] + f"_{lang}.json")
        out.write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n")
        print(f"{lang}: wrote {out.name} (post_on {st.get('post_on')}, feature {st.get('feature')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
