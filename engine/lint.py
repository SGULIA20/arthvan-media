"""Guardrails and caption building. A non-empty lint result means: do not post this item."""
import re

from .config import load_global

_DIGIT = re.compile(r"\d")
MAX_CAPTION = 2200
MAX_TAGS = 5


def _phrase_pattern(phrase: str) -> re.Pattern:
    lead = r"\b" if phrase[:1].isalnum() else ""
    tail = r"\b" if phrase.endswith(" ") else ""
    return re.compile(lead + re.escape(phrase.strip()) + tail, re.I)


def _segments(item: dict):
    """Yield (where, text, is_sample, check_digits)."""
    yield "caption", item.get("caption", ""), False, True
    if item.get("reel_caption"):
        yield "reel_caption", item["reel_caption"], False, True
    for tag in item.get("hashtags", []):
        yield "hashtag", tag, False, False
    for i, s in enumerate(item.get("slides", [])):
        sample = bool(s.get("sample"))
        where = f"slide {i}"
        if s.get("kind") == "stat":
            yield where, f"{s.get('value', '')} {s.get('text', '')}", sample, True
        else:
            yield where, s.get("text", ""), sample, True
        if s.get("sub"):
            yield where, s["sub"], sample, True
        for it in s.get("items", []):
            yield where, it, sample, True
        for r in s.get("rows", []):
            yield where, f"{r.get('label', '')} {r.get('display', '')}", sample, True


def lint_item(app_cfg: dict, item: dict) -> list:
    glob = load_global()
    banned = [(p, _phrase_pattern(p)) for p in glob["banned_phrases"] + app_cfg["banned_phrases"]]
    allowed = [re.compile(re.escape(a), re.I) for a in app_cfg["allowed_numbers"]]
    counts = re.compile(r"\b\d+\s+(?:%s)\b" % "|".join(glob["allowed_count_words"]), re.I)
    problems = []
    for where, text, sample, check_digits in _segments(item):
        for phrase, pat in banned:
            if pat.search(text):
                problems.append(f"{where}: banned phrase {phrase.strip()!r}")
        if check_digits and not sample:
            clean = text
            for a in allowed:
                clean = a.sub(" ", clean)
            clean = counts.sub(" ", clean)
            if _DIGIT.search(clean):
                problems.append(f"{where}: number without a sample flag in {text!r}")
    has_sample = any(s.get("sample") for s in item.get("slides", []))
    if has_sample and not app_cfg.get("money_disclaimer"):
        problems.append("sample slides need a money_disclaimer for this app")
    if len(item.get("hashtags", [])) > MAX_TAGS:
        problems.append("more than 5 hashtags")
    try:
        for cap in build_captions(app_cfg, item):
            if len(cap) >= MAX_CAPTION:
                problems.append("caption too long")
    except KeyError as e:
        problems.append(f"cannot build captions: {e}")
    return problems


def build_captions(app_cfg: dict, item: dict) -> tuple:
    footer = "\n".join(line.format(play_url=app_cfg["play_url"]) for line in app_cfg["footer"])
    has_sample = any(s.get("sample") for s in item["slides"])
    disclaimer = app_cfg.get("money_disclaimer") if has_sample else None
    tags = list(dict.fromkeys(item["hashtags"] + app_cfg["base_hashtags"]))[:MAX_TAGS]

    def make(body: str) -> str:
        parts = [body, footer]
        if disclaimer:
            parts.append(disclaimer)
        parts.append(" ".join(tags))
        return "\n\n".join(parts)

    return make(item["caption"]), make(item.get("reel_caption", item["caption"]))
