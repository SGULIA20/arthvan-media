"""The two live LinkedIn categories, markets and news, written the evening before they go out (founder, 21 Nov 2026: "Auto, with a
fact gate"; posts publish without his approval, so nothing unproven may pass).

One Claude request researches with web search and writes the post; a second, separate request checks every claim against the web
again. The post is used only when all of these hold, otherwise the caller posts a ready one from the bank:

  1. every source link is a page the search really returned in that request (no invented links);
  2. every claim has two sources on different sites;
  3. every number in the post appears in a claim;
  4. a markets post's figures are dated within the last few days;
  5. the post passes the lane's own checks (length, hype words, hashtags, no topic the founder already posted);
  6. the second request confirms each claim.

Raw HTTP like engine/write_story.py: this repo carries no Anthropic SDK.
"""
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .config import ROOT

MODEL = os.environ.get("LINKEDIN_LIVE_MODEL", "claude-opus-5-5")
API = "https://api.anthropic.com/v1/messages"
SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}
MAX_TURNS = 4                          # a long search turn can pause; it is resumed this many times at most
FRESH_DAYS = 4                         # a markets figure older than this is not "current"
BRIEF = "content/prompts/linkedin-brief.md"
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
ASK = {"markets": "a current move in financial markets or the economy (gold, crypto, stock markets, interest rates and inflation, oil and "
                  "commodities, currencies, central banks, emerging markets) and what it means for a business",
       "news": "one significant development of the last few days at a major company or group (Tata, Reliance, Adani, Mahindra, Infosys, "
               "Microsoft, Apple, Google, Amazon, Tesla, Nvidia, Toyota, Samsung, a global bank, a large manufacturer, an African "
               "conglomerate) and its business implications"}


class LiveError(Exception):
    pass


def call(messages: list, system: str, key: str = None, model: str = MODEL) -> dict:
    """One Messages request with web search, resumed while the turn is paused. Returns {"text", "urls"}: the final text and every
    page address the search returned."""
    key = key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LiveError("ANTHROPIC_API_KEY is not set")
    messages, urls, text = list(messages), set(), ""
    for _ in range(MAX_TURNS):
        body = {"model": model, "max_tokens": 16000, "system": system, "tools": [SEARCH], "messages": messages,
                "output_config": {"effort": "high"}}
        req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST",
                                     headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=600, context=ssl.create_default_context()) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            raise LiveError(f"Claude failed ({e.code}): {e.read()[:200].decode(errors='replace').replace(key, '<key>')}")
        for b in d.get("content", []):
            if b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):    # an error comes as an object, not a list
                urls |= {r.get("url") for r in b["content"] if r.get("type") == "web_search_result" and r.get("url")}
        text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        if d.get("stop_reason") == "pause_turn":
            messages.append({"role": "assistant", "content": d["content"]})
            continue
        if d.get("stop_reason") != "end_turn":
            raise LiveError(f"the writer stopped with {d.get('stop_reason')}")
        return {"text": text, "urls": urls}
    raise LiveError("the search turn did not finish")


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise LiveError("no JSON in the reply")
    try:
        return json.loads(m.group(0))
    except ValueError as e:
        raise LiveError(f"the reply is not valid JSON ({e})")


def _site(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return ".".join(host.split(".")[-2:])


def _numbers(text: str) -> set:
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(text or "")}


def write_prompt(category: str, day: date, covered: list) -> str:
    return (f"Today is {day:%A %d %B %Y}; the post goes out tomorrow morning. Category: {category}. Write about {ASK[category]}.\n\n"
            "Search the web first. Find three to five candidate topics, pick the one with the strongest mix of relevance, originality and "
            "value to a CEO, CFO or COO, then check its key figures in at least two credible sources on DIFFERENT sites (company filings "
            "and announcements, central banks, Reuters, Bloomberg, Financial Times and the like). Never assume a price or an index is "
            "rising or falling: read the latest move, its period and its date.\n\n"
            f"Already covered recently, do not repeat these subjects: {'; '.join(covered[-25:]) or 'none'}.\n\n"
            "Write the post to the brief: a hook of at most 140 characters, a body of 105 to 140 words that gives the real story with its "
            "figures, why it happened and what it costs or changes, the management lesson, and ONE line of the author's view as a finance "
            "and operations leader, then one closing question. Do not invent a personal anecdote, a place he was or anything he did. "
            "No investment advice: never say to buy, sell or hold, and no price forecast. No em-dashes, no emojis.\n\n"
            "Reply with JSON only, exactly this shape:\n"
            '{"id": "short-kebab-id", "hook": "...", "body": "...", "question": "...?", "hashtags": ["#A", "#B", "#C"], '
            '"card": {"title": "at most 60 characters", "points": ["at most 70 characters each, 3 to 5 points"], "source": "the main sources, short"}, '
            '"scene": "one photorealistic scene for the picture: a place or object, no text, no logos, no real person", '
            '"as_of": "YYYY-MM-DD, the date of the latest figure in the post", '
            '"claims": [{"claim": "one checkable statement exactly as the post makes it, with its figures", "sources": ["url", "url"]}]}\n'
            "Every number in the hook, the body and the card must appear in a claim, and every source must be a page your search returned.")


def gate(post: dict, urls: set, category: str, day: date, settings: dict) -> list:
    """Checks 1 to 5. A non-empty result means: do not post this."""
    from . import linkedin_personal as lp
    problems = []
    claims = post.get("claims") or []
    if not claims:
        problems.append("no claims listed")
    for c in claims:
        srcs = [s for s in (c.get("sources") or []) if isinstance(s, str)]
        unseen = [s for s in srcs if s not in urls]
        if unseen:
            problems.append(f"a source the search did not return: {unseen[0][:80]}")
        if len({_site(s) for s in srcs if s in urls}) < 2:
            problems.append(f"fewer than two sites back: {str(c.get('claim'))[:70]}")
    card = post.get("card") or {}
    shown = " ".join([str(post.get("hook", "")), str(post.get("body", "")), str(card.get("title", "")), " ".join(card.get("points") or [])])
    missing = _numbers(shown) - _numbers(" ".join(str(c.get("claim", "")) for c in claims))
    if missing:
        problems.append(f"numbers in the post that no claim covers: {', '.join(sorted(missing)[:6])}")
    if category == "markets":
        try:
            age = (day - date.fromisoformat(str(post.get("as_of")))).days
        except ValueError:
            age = None
        if age is None or not 0 <= age <= FRESH_DAYS:
            problems.append(f"the market figures are dated {post.get('as_of')!r}, not within {FRESH_DAYS} days")
    item = to_item(post, category)
    return problems + lp.lint_personal(item, settings)


def to_item(post: dict, category: str) -> dict:
    claims = post.get("claims") or []
    facts = "; ".join(f"{c.get('claim')} [{', '.join(_site(s) for s in c.get('sources') or [])}]" for c in claims)[:1500]
    return {"id": f"live-{str(post.get('id') or category)[:40]}", "pillar": category, "hook": str(post.get("hook", "")).strip(),
            "body": str(post.get("body", "")).strip(), "question": str(post.get("question", "")).strip(),
            "hashtags": [h for h in post.get("hashtags") or [] if isinstance(h, str)][:4], "card": post.get("card") or {},
            "scene": str(post.get("scene") or ""), "facts": facts or "", "as_of": post.get("as_of"),
            "sources": sorted({s for c in claims for s in c.get("sources") or []})[:8]}


def verify_prompt(post: dict, day: date) -> str:
    claims = [c.get("claim") for c in post.get("claims") or []]
    return (f"Today is {day:%d %B %Y}. A post is about to be published under a finance executive's name. Check each claim below "
            "against the web yourself; do not trust the claim's wording. A claim is true only if you find it confirmed, with its figures "
            "and dates, by a credible source. Also say whether the hook is supported by the facts.\n\n"
            f"Hook: {post.get('hook')}\nClaims:\n" + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(claims)) +
            '\n\nReply with JSON only: {"claims": [{"n": 1, "true": true, "note": "short"}], "hook_supported": true}')


def write(category: str, day: date, covered: list, settings: dict, *, root: Path = ROOT, ask=call):
    """(post ready for the lane, "") or (None, why not). Never raises: the caller falls back to the bank."""
    try:
        system = (Path(root) / BRIEF).read_text()
        first = ask([{"role": "user", "content": write_prompt(category, day, covered)}], system)
        post = _json(first["text"])
        problems = gate(post, first["urls"], category, day, settings)
        if problems:
            return None, "; ".join(problems[:3])
        check = _json(ask([{"role": "user", "content": verify_prompt(post, day)}],
                          "You are a careful fact checker. Search before you answer.")["text"])
        rows = check.get("claims") or []
        bad = [r for r in rows if r.get("true") is not True]
        if len(rows) < len(post["claims"]) or bad or check.get("hook_supported") is not True:
            why = (bad[0].get("note") if bad else "") or "the hook is not supported, or a claim was left unchecked"
            return None, f"the second check did not confirm it: {str(why)[:160]}"
        return to_item(post, category), ""
    except (LiveError, OSError, KeyError, TypeError) as e:
        return None, f"{type(e).__name__}: {str(e)[:160]}"
