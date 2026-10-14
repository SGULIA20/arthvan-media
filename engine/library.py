"""The founder's Reel library on the Desktop, organised App -> Language -> complete Reels:

    ~/Desktop/Arthvan-Reels/ScoreMyBiz/English/01-lumi-daily-en.mp4
    ~/Desktop/Arthvan-Reels/ScoreMyBiz/Hindi/01-lumi-daily-hi.mp4
    ~/Desktop/Arthvan-Reels/Waypoint/English/...

stories/out/<id>.mp4 stays the source of truth (it is what the daily post reads); this library is the founder's copy. Numbers run per folder,
in the order made. A Reel already filed is never replaced by filing; `sync` is the one deliberate refresh (after a re-render).
python -m engine.library migrate   move any old flat NN-id.mp4 files into the folders (nothing is deleted)
python -m engine.library sync      file new Reels and refresh any whose finished video changed
python -m engine.library coverage how many Reels each language has against English, per app"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = Path.home() / "Desktop" / "Arthvan-Reels"
APPS = {"scoremybiz": "ScoreMyBiz", "waypoint": "Waypoint", "quiethand": "QuietHand"}
LANGUAGES = {"en": "English", "hi": "Hindi", "gu": "Gujarati", "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "bn": "Bengali", "kn": "Kannada",
             "ml": "Malayalam", "pa": "Punjabi", "ur": "Urdu", "or": "Odia", "as": "Assamese", "es": "Spanish", "pt": "Portuguese", "fr": "French",
             "de": "German", "it": "Italian", "nl": "Dutch", "fi": "Finnish", "id": "Indonesian", "ar": "Arabic", "sw": "Swahili", "yo": "Yoruba",
             "ha": "Hausa", "ig": "Igbo"}


def story_info(story_id: str, root: Path = ROOT):
    """(app, language code) of a story, or None when its script is not found."""
    p = Path(root) / "stories" / (story_id.replace("-", "_") + ".json")
    if not p.exists():
        return None
    st = json.loads(p.read_text())
    return st["app"], st.get("lang", "en").split("-")[0]


def folder_for(app: str, lang: str, library: Path = LIBRARY) -> Path:
    return Path(library) / APPS.get(app, app.title()) / LANGUAGES.get(lang, lang)


def _number(f: Path):
    n = f.name.split("-", 1)[0]
    return int(n) if n.isdigit() else None


def find(story_id: str, library: Path = LIBRARY):
    for f in Path(library).rglob("*.mp4"):
        if _number(f) is not None and f.stem.split("-", 1)[-1] == story_id:
            return f
    return None


def file_reel(mp4: Path, story_id: str, library: Path = LIBRARY, root: Path = ROOT) -> Path:
    """Copy a finished Reel into its App/Language folder. One already there is never replaced."""
    library = Path(library)
    have = find(story_id, library)
    if have:
        return have
    info = story_info(story_id, root)
    folder = folder_for(*info, library) if info else library          # a script we cannot find is filed at the top, as before
    folder.mkdir(parents=True, exist_ok=True)
    nums = [_number(f) for f in folder.glob("*.mp4") if _number(f) is not None]
    dst = folder / f"{(max(nums) + 1 if nums else 1):02d}-{story_id}.mp4"
    shutil.copy2(mp4, dst)
    return dst


def migrate(library: Path = LIBRARY, root: Path = ROOT) -> list:
    """Move old flat NN-id.mp4 files (in their old order) into the folders. Nothing is deleted or overwritten."""
    library, moved = Path(library), []
    flat = sorted((f for f in library.glob("*.mp4") if _number(f) is not None), key=_number)
    for f in flat:
        sid = f.stem.split("-", 1)[-1]
        info = story_info(sid, root)
        if not info:
            continue
        folder = folder_for(*info, library); folder.mkdir(parents=True, exist_ok=True)
        nums = [_number(x) for x in folder.glob("*.mp4") if _number(x) is not None]
        dst = folder / f"{(max(nums) + 1 if nums else 1):02d}-{sid}.mp4"
        shutil.move(str(f), str(dst)); moved.append((f.name, str(dst.relative_to(library))))
    return moved


def sync(library: Path = LIBRARY, root: Path = ROOT) -> dict:
    """File every finished Reel in stories/out that the library lacks, and refresh the ones whose finished video has changed."""
    out = {"filed": [], "refreshed": []}
    for mp4 in sorted((Path(root) / "stories" / "out").glob("*.mp4")):
        sid = mp4.stem
        have = find(sid, library)
        if have is None:
            if story_info(sid, root):
                out["filed"].append(str(file_reel(mp4, sid, library, root).relative_to(library)))
        elif have.stat().st_size != mp4.stat().st_size:
            shutil.copy2(mp4, have); out["refreshed"].append(str(have.relative_to(library)))
    return out


# ---------- language coverage: every English Reel should exist in every target language ----------
TARGETS = ["hi", "gu", "mr", "ta", "te", "bn", "kn", "ml", "ur"]          # Indian languages whose Google voice was verified (Waypoint/ScoreMyBiz both have them)


def _base(story_id: str) -> str:
    return story_id.rsplit("-", 1)[0]


def coverage(root: Path = ROOT, targets: list = None) -> dict:
    """{app: {"english": n, "rows": [{lang, name, made, scripted, todo, own}]}}.
    English is the yardstick: its Reels that can be posted (no claims problem, not a multi-language Reel), finished or scripted.
    made = finished in that language, scripted = script written but video not made yet, todo = not started, own = Reels in that
    language with no English twin (the festival Reels)."""
    from . import calendar_plan
    root = Path(root); targets = targets or TARGETS
    done = {p.stem for p in (root / "stories" / "out").glob("*.mp4")}
    held = {s["id"] for s in calendar_plan.load_stories(root) if s["problems"]}
    stories = [json.loads(p.read_text()) for p in sorted((root / "stories").glob("*.json"))]
    out = {}
    for app in APPS:
        mine = [s for s in stories if s["app"] == app and s["id"] not in held and not any("native" in sc for sc in s["scenes"])]
        eng = {_base(s["id"]) for s in mine if s.get("lang", "en").split("-")[0] == "en"}
        if not eng:
            continue
        langs = list(targets) + sorted({s.get("lang", "en").split("-")[0] for s in mine} - {"en"} - set(targets))
        rows = []
        for lang in langs:
            theirs = [s for s in mine if s.get("lang", "en").split("-")[0] == lang]
            made = {_base(s["id"]) for s in theirs if s["id"] in done}
            scripted = {_base(s["id"]) for s in theirs if s["id"] not in done}
            rows.append({"lang": lang, "name": LANGUAGES.get(lang, lang), "made": len(made & eng), "scripted": len(scripted & eng - made),
                         "todo": len(eng - made - scripted), "own": len((made | scripted) - eng)})
        out[app] = {"english": len(eng), "english_made": len({_base(s["id"]) for s in mine if s["id"] in done and s.get("lang", "en").split("-")[0] == "en"}), "rows": rows}
    return out


def coverage_text(root: Path = ROOT) -> str:
    lines = []
    for app, c in coverage(root).items():
        lines.append(f"{APPS[app]}: {c['english']} English Reels ({c['english_made']} made). Every language should have the same {c['english']}.")
        for r in c["rows"]:
            own = f", plus {r['own']} festival Reel{'s' if r['own'] != 1 else ''} of its own" if r["own"] else ""
            lines.append(f"  {r['name']:<10} made {r['made']:>2} of {c['english']:>2} | scripted, video not made {r['scripted']:>2} | not started {r['todo']:>2}{own}")
    return "\n".join(lines)


def coverage_html(root: Path = ROOT) -> str:
    out = []
    for app, c in coverage(root).items():
        rows = "".join(f"<tr><td>{r['name']}</td><td style='text-align:right'><b>{r['made']}</b> of {c['english']}</td><td style='color:#b8860b'>+{r['scripted']} scripted</td>"
                       f"<td style='color:#d33'>{r['todo']} not started</td></tr>" for r in c["rows"])
        out.append(f"<h3>{APPS[app]}: {c['english']} English Reels, every language needs the same</h3><table cellpadding=5>{rows}</table>")
    return "".join(out)


def main(argv=None) -> int:
    cmd = (sys.argv[1:] if argv is None else argv)[:1]
    if cmd == ["migrate"]:
        for a, b in migrate():
            print(f"moved {a} -> {b}")
    elif cmd == ["coverage"]:
        print(coverage_text())
    elif cmd == ["sync"]:
        r = sync(); print(f"filed {len(r['filed'])}, refreshed {len(r['refreshed'])}"); [print("  +", x) for x in r["filed"]]; [print("  ~", x) for x in r["refreshed"]]
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
