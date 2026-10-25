"""Story Reels open on the hook, not a greeting (founder, 25 Oct 2026). The app Reels opened "Hi, I'm Lumi" / "Hi. This is
Imtiaz's story" and 54-80 % of viewers swiped away in the first 3 seconds. A Reel that is already rendered goes out as made.

opening_problems(story)   what a render refuses: a greeting or a self-introduction first, or a first sentence over HOOK_WORDS_MAX
rewrite(story, ask)       the first scene rewritten by Gemini in the story's own language, checked before it is kept
python -m engine.story_hook [--write]    every story not yet rendered; prints the changes, --write saves them
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

from . import gemini
from .library import LANGUAGES

ROOT = Path(__file__).resolve().parent.parent
HOOK_WORDS_MAX = 14
SPLIT = re.compile(r"(?<=[.!?।])\s+")
GREETINGS = ("hi", "hello", "hey", "namaste", "namaskar", "नमस्ते", "नमस्कार", "हाय", "हैलो", "हॅलो", "હાય", "નમસ્તે", "નમસ્કાર", "હેલો",
             "ஹாய்", "வணக்கம்", "হাই", "নমস্কার", "হ্যালো")
STORY_WORDS = ("story", "कहानी", "कथा", "गोष्ट", "વાર્તા", "વાત", "કહાણી", "கதை", "গল্প")
SELF = ("i'm lumi", "i am lumi", "i'm mira", "i am mira", "मैं लूमी", "मैं मीरा", "मी लुमी", "मी मीरा", "હું લુમી", "હું મીરા",
        "நான் லூமி", "நான் மீரா", "আমি লুমি", "আমি মীরা")
PROMPT = """Below is the first spoken scene of a 30-second Instagram Reel for a mobile app, in {language}.
Rewrite it so the VERY FIRST sentence is the hook: the problem, the surprising moment or a direct question, at most 10 words.
- Remove any greeting (Hi, Hello, Namaste...) and any "This is X's story" or "I'm Lumi/Mira" introduction.
- If the text names a person, keep the name in the first or second sentence so "he/she/his" always has someone to point to.
- Keep everything else that follows, same meaning, same language and script ({language}), everyday spoken words. No new facts and no numbers that are not in the input.
- About the same length as the input or shorter.
Return ONLY the rewritten scene text, nothing else.

Scene text:
{vo}"""


def _bare(s: str) -> str:
    return re.sub(r"[\s.,!?।:;]+", " ", s).strip().lower()


def _slow(sentence: str) -> bool:
    b = _bare(sentence)
    words = b.split()
    return bool(words) and (words[0] in GREETINGS or (len(sentence) <= 60 and (any(w in b for w in SELF) or any(w in b for w in STORY_WORDS))))


def opening_problems(story: dict) -> list:
    scenes = story.get("scenes") or []
    vo = str((scenes[0] if scenes else {}).get("vo") or "").strip()
    if not vo or story.get("occasion"):                 # a festival greeting is the point of an occasion Reel
        return []
    first = SPLIT.split(vo)[0]
    out = []
    if _slow(first):
        out.append(f"opening: starts with a greeting or an introduction ({first[:40]!r}); open on the problem or the question")
    n = len(_bare(first).split())
    if n > HOOK_WORDS_MAX:
        out.append(f"opening: first sentence is {n} words, at most {HOOK_WORDS_MAX}")
    return out


def check_rewrite(old: str, new: str) -> list:
    out = []
    if not new.strip():
        return ["empty"]
    probe = {"scenes": [{"vo": new}]}
    out += opening_problems(probe)
    if len(new) > 1.25 * len(old) + 20:
        out.append("longer than the original")
    if set(re.findall(r"\d+", new)) - set(re.findall(r"\d+", old)):
        out.append("a number that is not in the original")
    latin = lambda s: sum(c.isascii() and c.isalpha() for c in s) / max(1, sum(c.isalpha() for c in s))
    if abs(latin(old) - latin(new)) > 0.35:
        out.append("not in the original script")
    return out


def rewrite(story: dict, ask=gemini.ask) -> tuple:
    """(new first-scene text, problems). The story is not changed here."""
    old = str(story["scenes"][0].get("vo") or "")
    lang = story.get("lang", "en").split("-")[0]
    new = ask(PROMPT.format(language=LANGUAGES.get(lang, lang), vo=old), max_tokens=600).strip().strip('"').strip()
    return new, check_rewrite(old, new)


def apply(story: dict, new: str) -> dict:
    sc = story["scenes"][0]
    if sc.get("sub") == sc.get("vo"):
        sc["sub"] = new
    sc["vo"] = new
    story["hook_rewritten"] = date.today().isoformat()
    return story


def pending(root: Path = ROOT) -> list:
    rendered = {p.stem for p in (root / "stories" / "out").glob("*.mp4")}
    out = []
    for p in sorted((root / "stories").glob("*.json")):
        st = json.loads(p.read_text())
        if st["id"] not in rendered and opening_problems(st):
            out.append((p, st))
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    todo, kept, refused = pending(), 0, []
    for path, st in todo:
        try:
            new, problems = rewrite(st)
        except Exception as e:                                   # noqa: BLE001  one story's failure never stops the rest
            refused.append(f"{st['id']}: {type(e).__name__}: {str(e)[:100]}")
            continue
        if problems:
            refused.append(f"{st['id']}: {'; '.join(problems)} -> {new[:80]!r}")
            continue
        print(f"{st['id']}:\n  - {st['scenes'][0]['vo'][:140]}\n  + {new[:140]}", flush=True)
        if "--write" in argv:
            path.write_text(json.dumps(apply(st, new), ensure_ascii=False, indent=1) + "\n")
        kept += 1
    print(f"\n{len(todo)} stories to fix, {kept} rewritten, {len(refused)} refused (they will not render until fixed by hand):")
    for r in refused:
        print("  ", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
