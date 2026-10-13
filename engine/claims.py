"""No false or premature claims: a Reel or post may only show features that are fully live in the apps.

content/features.json holds the verified status of every feature (from the apps' own code); content/screen_features.json
says which feature each captured screen shows. A story whose feature or screens are gated, partial or not live is held
back automatically, and a graphics post whose feature is not live is never picked.
"""
import json
from pathlib import Path

from .config import ROOT

OK = ("live", "general")


def load(root: Path = ROOT):
    feats = json.loads((Path(root) / "content" / "features.json").read_text()) if (Path(root) / "content" / "features.json").exists() else {}
    smap = json.loads((Path(root) / "content" / "screen_features.json").read_text()) if (Path(root) / "content" / "screen_features.json").exists() else {}
    return feats, smap


def feature_problem(app: str, key, feats: dict):
    cat = (feats.get(app) or {})
    if not cat or not key:
        return None                                   # no catalogue for this app yet: nothing to check against
    f = cat.get(key)
    if f is None:
        return f"feature '{key}' is not in the verified catalogue"
    if f.get("status") not in OK and not f.get("show_ok"):
        return f"feature '{key}' is {f.get('status')}" + (f" ({str(f.get('gate'))[:60]})" if f.get("gate") else "")
    return None


def story_problems(story: dict, feats: dict, smap: dict) -> list:
    app = story["app"]; out = []
    p = feature_problem(app, story.get("feature"), feats)
    if p:
        out.append(p)
    if story.get("hold"):
        out.append(f"on hold: {story['hold']}")
    for i, sc in enumerate(story.get("scenes", [])):
        shot = sc.get("screen")
        if shot and (smap.get(app) or {}):
            key = smap[app].get(shot)
            if key is None:
                out.append(f"scene {i}: screen {shot} is not mapped to a verified feature")
            else:
                q = feature_problem(app, key, feats)
                if q:
                    out.append(f"scene {i}: shows {shot}: {q}")
    return out


def item_problems(app: str, item: dict, feats: dict) -> list:
    out = []
    if item.get("hold"):
        out.append(f"on hold: {item['hold']}")
    p = feature_problem(app, item.get("feature"), feats)
    if p:
        out.append(p)
    return out
