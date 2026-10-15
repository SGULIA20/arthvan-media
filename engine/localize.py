"""Localized versions of finished Reels. The filmed shots, characters, screens and timing are language-neutral and already paid for,
so a version in another language costs NO video credit: it needs a translated script (content/translations/<lang>/<story id>.json),
a fresh voice (one Google voice request per line) and, for screens not yet captured in that language, the English screens.

content/translations/hi/lumi-daily-en.json = {"title", "caption", "scenes": [{"vo": "...", "sub": "... (optional, defaults to vo)", "card": "... (optional)"}, ...]}
python -m engine.localize hi        writes stories/<id>-hi.json for every translation file of that language
Translations are drafts until a native speaker has read them."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALE = {"hi": "hi-IN"}


def localized_id(base_id: str, lang: str) -> str:
    return f"{base_id[:-3] if base_id.endswith('-en') else base_id}-{lang}"


def localize(base: dict, tr: dict, lang: str) -> dict:
    if len(tr["scenes"]) != len(base["scenes"]):
        raise ValueError(f"{base['id']}: translation has {len(tr['scenes'])} scenes, the Reel has {len(base['scenes'])} scenes")
    st = copy.deepcopy(base)
    for k in [k for k in st if k.startswith("_")]:          # the loader's private flags (like _held) do not belong in a story file
        del st[k]
    st["id"], st["lang"] = localized_id(base["id"], lang), LOCALE.get(lang, lang)
    for k in ("legacy", "voice", "rate"):
        st.pop(k, None)
    for sc, t in zip(st["scenes"], tr["scenes"]):
        sc["vo"] = t["vo"]
        if sc.get("layout") != "end":
            sc["sub"] = t.get("sub", t["vo"])
        if "card" in t:
            sc["card"] = t["card"]
    for k in ("title", "caption"):
        if k in tr:
            st[k] = tr[k]
    if tr.get("post_on"):
        st["post_on"] = tr["post_on"]
    return st


def main(argv=None) -> int:
    lang = (sys.argv[1:] if argv is None else argv)[0]
    made = []
    for f in sorted((ROOT / "content" / "translations" / lang).glob("*.json")):
        base = json.loads((ROOT / "stories" / (f.stem.replace("-", "_") + ".json")).read_text())
        st = localize(base, json.loads(f.read_text()), lang)
        out = ROOT / "stories" / (st["id"].replace("-", "_") + ".json")
        out.write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n"); made.append(st["id"])
    print("wrote", len(made), "Reels:", ", ".join(made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
