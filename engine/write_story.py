"""Write a NEW illustrated story Reel for a feature no story has shown yet (founder, 8 Nov 2026: "n features on both apps, so every
time a new feature story should be posted").

    python -m engine.write_story scoremybiz            # picks the next unshown live feature, writes stories/lumi_<feature>_hi.json
    python -m engine.write_story waypoint --feature polls

Claude (ANTHROPIC_API_KEY) writes the script from the verified feature entry in content/features.json only; engine.claims then checks
the feature and every screen; the pictures and voice are made afterwards by engine.illustrate / engine.story (workflow write-story).
Hindi is the base language (voice in Devanagari, subtitles romanized); engine.story_localize makes the other languages.
"""
import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import claims
from .config import ROOT

MODEL = os.environ.get("STORY_WRITER_MODEL", "claude-sonnet-5-5")
CHARACTER = {"scoremybiz": "lumi", "waypoint": "mira"}
HASHTAGS = {"scoremybiz": ["#ScoreMyBiz", "#SmallBusiness", "#HindiReels"], "waypoint": ["#Waypoint", "#HindiReels"]}
CTA = {"scoremybiz": "ScoreMyBiz, 30 din muft: link in bio.", "waypoint": "Waypoint, link in bio. 18+"}


class WriterError(Exception):
    pass


def covered_features(app: str, root: Path = ROOT) -> set:
    """Features that already have a story file of this app's character (any language)."""
    out = set()
    for p in Path(root).glob("stories/*.json"):
        try:
            s = json.loads(p.read_text())
        except ValueError:
            continue
        if s.get("app") == app and s.get("feature") and s.get("character") == CHARACTER[app]:
            out.add(s["feature"])
    return out


def feature_screens(app: str, feature: str, smap: dict, root: Path = ROOT) -> list:
    base = Path(root) / "store" / "shots" / app
    shots = [n for n, k in (smap.get(app) or {}).items() if k == feature]
    return [n for n in shots if any((base / d / n).exists() for d in ("hi", "en"))]


def pick_feature(app: str, feats: dict, smap: dict, root: Path = ROOT, only: str = None):
    """The first live, demo-able feature with a captured screen that has no story yet (catalogue order)."""
    cat = feats.get(app) or {}
    done = covered_features(app, root)
    for key, f in cat.items():
        if only and key != only:
            continue
        if not only and key in done:
            continue
        if claims.feature_problem(app, key, feats) or not f.get("demo_possible"):
            continue
        if feature_screens(app, key, smap, root):
            return key
    return None


PROMPT = """You write one 40-second illustrated story Reel in Hindi for the app {app_name}.

THE ONE FEATURE (use only these facts, add no other claim about the app):
name: {name}
what it does: {summary}
safe wording: {safe}
story idea: {hook}
never use these words: {avoid}

Rules:
- A human story first (a shopkeeper, a daughter, a friend), the feature appears as the thing that helps. No pricing, no "buy", no guarantees, no health or income promises.
- 11 to 13 scenes. Scene kinds: "illus" (a picture), "phone" (one of these app screens, shown full: {screens}; use 1 to 3 phone scenes, each at the moment the story uses the feature), then a final "illus" question to the viewer, then nothing else (the end card is added by us).
- "vo" is the Hindi voice line in Devanagari, one short sentence (6-12 words). "sub" is the same line in Roman letters (Hinglish), starting with a capital letter.
- "art" (illus scenes only) is an English picture description: who, where, light, one action. Use only the cast names you define.
- Reply with JSON only, no prose, exactly this shape:
{{"title": "...", "banner": "short line<br><em>key words</em> emoji", "caption": "2-3 lines in Hinglish ending with a question and 👇",
 "linkedin_text": "2 English sentences describing the story, no claims beyond the facts", "cast": {{"Name": "one-sentence look"}},
 "scenes": [{{"kind": "illus", "vo": "...", "sub": "...", "art": "..."}}, {{"kind": "phone", "vo": "...", "sub": "...", "screen": "name.png"}}]}}"""


def ask_claude(prompt: str, key: str = None, model: str = MODEL, max_tokens: int = 4000) -> str:
    key = key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise WriterError("ANTHROPIC_API_KEY is not set")
    body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=180, context=ssl.create_default_context()) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        raise WriterError(f"Claude failed ({e.code}): {e.read()[:200].decode(errors='replace').replace(key, '<key>')}")
    return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise WriterError("no JSON in the answer")
    try:
        return json.loads(m.group(0))
    except ValueError as e:
        raise WriterError(f"bad JSON: {e}")


def build(app: str, feature: str, raw: dict, template: dict, feats: dict, smap: dict, root: Path = ROOT) -> dict:
    """Turn the writer's answer into a story file in the house schema; raise WriterError if it breaks a rule."""
    f = feats[app][feature]
    char = CHARACTER[app]
    allowed = set(feature_screens(app, feature, smap, root))
    scenes, n = [], 0
    for sc in raw.get("scenes", []):
        vo, sub = (sc.get("vo") or "").strip(), (sc.get("sub") or "").strip()
        if not vo or not sub:
            raise WriterError("a scene has no voice or subtitle line")
        if sc.get("kind") == "phone":
            if sc.get("screen") not in allowed:
                raise WriterError(f"screen {sc.get('screen')} is not one of this feature's screens {sorted(allowed)}")
            scenes.append({"layout": "phone", "vo": vo, "sub": sub, "min": 2.4, "screen": sc["screen"]})
        else:
            n += 1
            if not (sc.get("art") or "").strip():
                raise WriterError("a picture scene has no art description")
            scenes.append({"layout": "illus", "image": f"s{len(scenes) + 1:02d}.png", "vo": vo, "sub": sub, "min": 2.2, "art": sc["art"].strip(), "noref": True})
    if not 9 <= len(scenes) <= 14 or n < 6 or not any(s["layout"] == "phone" for s in scenes):
        raise WriterError(f"unusable shape: {len(scenes)} scenes, {n} pictures")
    scenes[-1]["focus"] = "50% 45%"
    scenes[-1]["min"] = 3.0
    scenes.append({"layout": "end", "pose": "front_happy", "vo": template_end_vo(app), "sub": "", "min": 5})
    sid = f"{char}-{feature}-hi"
    art = json.loads(json.dumps(template["art"]))
    art["cast"] = {str(k): str(v) for k, v in (raw.get("cast") or {}).items()} or art.get("cast", {})
    story = {"id": sid, "app": app, "lang": "hi-IN", "character": char, "feature": feature, "style": "cutout", "pad": 0.4,
             "title": raw["title"], "banner": raw["banner"], "caption": raw["caption"].rstrip() + "\n" + CTA[app],
             "linkedin_text": raw["linkedin_text"], "hashtags": HASHTAGS[app], "art": art, "scenes": scenes}
    bad = claims.story_problems(story, feats, smap)
    avoid = [w for w in (f.get("avoid_words") or []) if w and w.lower() in json.dumps(story, ensure_ascii=False).lower()]
    if avoid:
        bad.append("uses avoided words: " + ", ".join(avoid))
    if bad:
        raise WriterError("; ".join(bad))
    return story


def template_end_vo(app: str) -> str:
    return "स्कोर माय बिज़। तीस दिन मुफ़्त।" if app == "scoremybiz" else "वेपॉइंट। गूगल प्ले पर मुफ़्त।"


def write(app: str, only: str = None, root: Path = ROOT, ask=ask_claude, tries: int = 2):
    feats, smap = claims.load(root)
    feature = pick_feature(app, feats, smap, root, only)
    if not feature:
        print(f"{app}: every live feature already has a story")
        return None
    f = feats[app][feature]
    tmpl_path = sorted(Path(root).glob(f"stories/{CHARACTER[app]}_*_hi.json"))[0]
    template = json.loads(tmpl_path.read_text())
    prompt = PROMPT.format(app_name={"scoremybiz": "ScoreMyBiz", "waypoint": "Waypoint (an anonymous peer-support app for adults 18+; never imply therapy or crisis help)"}[app],
                           name=f["name"], summary=f["summary"], safe=f.get("safe_wording", ""), hook=f.get("story_hook", ""),
                           avoid=", ".join(f.get("avoid_words") or []) or "none",
                           screens=", ".join(feature_screens(app, feature, smap, root)))
    err = None
    for _ in range(tries):
        try:
            story = build(app, feature, parse(ask(prompt + (f"\n\nYour last try was rejected: {err}. Fix that." if err else ""))), template, feats, smap, root)
            out = Path(root) / "stories" / (story["id"].replace("-", "_") + ".json")
            out.write_text(json.dumps(story, ensure_ascii=False, indent=1) + "\n")
            print(f"wrote {out.relative_to(root)} for feature {feature}")
            return story["id"]
        except WriterError as e:
            err = str(e)
            print(f"rejected: {err}", file=sys.stderr)
    raise WriterError(f"{feature}: {err}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("app", choices=sorted(CHARACTER))
    ap.add_argument("--feature")
    a = ap.parse_args(argv)
    sid = write(a.app, a.feature)
    if sid and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"story={sid}\n")
    return 0 if sid else 1


if __name__ == "__main__":
    sys.exit(main())
