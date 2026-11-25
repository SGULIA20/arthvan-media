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
CHECK_SEARCHES = 20                    # 21 Nov 2026: the second check ran out of its 8 searches before it had confirmed every claim
MAX_CLAIMS = 5                         # a short post rests on a few facts; more than this cannot be checked properly in one pass
MAX_TURNS = 4                          # a long search turn can pause; it is resumed this many times at most
FRESH_DAYS = 4                         # a markets figure older than this is not "current"
BRIEF = "content/prompts/linkedin-brief.md"
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
ASK = {"markets": "a current move in financial markets or the economy (gold, crypto, stock markets, interest rates and inflation, oil and "
                  "commodities, currencies, central banks, emerging markets) and what it means for a business",
       "news": "one significant development of the last few days at a major company or group (Tata, Reliance, Adani, Mahindra, Infosys, "
               "Microsoft, Apple, Google, Amazon, Tesla, Nvidia, Toyota, Samsung, a global bank, a large manufacturer, an African "
               "conglomerate) and its business implications",
       # founder, 25 Nov 2026: "You are free to choose any topic worldwide", chosen the way the channels now choose theirs
       "trend": "the ONE business, money, technology or work story that professionals around the world are talking about most in the "
                "last 72 hours: any country, any industry, any company. Judge 'most talked about' by evidence you can find: how many "
                "major outlets in different countries lead with it, and whether people DISAGREE about it. Prefer a story with a real "
                "argument in it (two defensible sides), a named company or person, and a number that surprises, because those are the "
                "posts people comment on. LinkedIn itself cannot be searched from here; do not claim a post or a hashtag is trending there"}
HOOKS = 6                              # openings written for one post; a panel of readers picks the one that goes out
FRESH = {"markets": FRESH_DAYS, "trend": 7}
PANEL = """Three people are scrolling LinkedIn on their phones in a spare minute. A: a CFO of a manufacturing group in Lagos. B: a
start-up founder in Bengaluru. C: a mid-level operations manager in London. Each sees ONLY the first line of a post, then decides
whether to tap "see more". They skip anything that sounds like a lecture, a press release or motivational talk, and stop for a named
company, a number that surprises them, or a claim they want to argue with.

Score each opening line below 0 to 10 for each reader: how likely that reader is to tap. Be hard; most lines deserve 3 to 5.
Reply with JSON only: {"scores": [[A, B, C], ...]} with one row per line, in order.

LINES
"""


# founder, 21 Nov 2026, after the first sample: what the second check must also confirm about the post as a whole
QUALITY = {"sources_credible": "a market figure without a primary or highly credible source",
           "expectations_clear": "an expectation worded as a decision",
           "causes_supported": "a cause stated without evidence",
           "three_parts": "what happened, why, and what a leader should do are not all there"}


class LiveError(Exception):
    pass


def call(messages: list, system: str, key: str = None, model: str = MODEL, searches: int = SEARCH["max_uses"]) -> dict:
    """One Messages request with web search (none when searches is 0), resumed while the turn is paused. Returns {"text", "urls"}:
    the final text and every page address the search returned."""
    key = key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LiveError("ANTHROPIC_API_KEY is not set")
    messages, urls, text = list(messages), set(), ""
    for _ in range(MAX_TURNS):
        body = {"model": model, "max_tokens": 16000, "system": system, "messages": messages, "output_config": {"effort": "high"},
                **({"tools": [{**SEARCH, "max_uses": searches}]} if searches else {})}
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


_TWO_PART = {"co.uk", "org.uk", "gov.uk", "ac.uk", "co.in", "gov.in", "org.in", "net.in", "com.au", "co.za", "com.ng", "gov.ng", "co.jp",
             "com.sg", "com.br", "co.nz", "com.cn", "co.kr", "com.hk"}


def _site(url: str) -> str:
    """The site a page belongs to: reuters.com, bbc.co.uk. Two pages of one site count once."""
    parts = (urlparse(url).hostname or "").lower().split(".")
    n = 3 if ".".join(parts[-2:]) in _TWO_PART else 2
    return ".".join(parts[-n:])


def _numbers(text: str) -> set:
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(text or "")}


def write_prompt(category: str, day: date, covered: list, lessons: str = "") -> str:
    return (f"Today is {day:%A %d %B %Y}; the post goes out tomorrow morning. Category: {category}. Write about {ASK[category]}.\n\n"
            "Search the web first. Find three to five candidate topics, pick the one with the strongest mix of relevance, originality and "
            "value to a CEO, CFO or COO, then check its key figures in at least two credible sources on DIFFERENT sites (company filings "
            "and announcements, central banks, Reuters, Bloomberg, Financial Times and the like). Never assume a price or an index is "
            "rising or falling: read the latest move, its period and its date.\n\n"
            "Three rules of accuracy (founder, 21 Nov 2026):\n"
            "1. Take every market figure from a primary or highly credible source: the exchange, the central bank, the company's own "
            "filing or statement, official statistics; Reuters, Bloomberg or the Financial Times for prices.\n"
            "2. Keep what markets EXPECT apart from what has been DECIDED. A probability implied by futures, a forecast or a bank's call is "
            "an expectation and must be worded as one ('futures price in', 'markets expect'); only an announced decision is a decision.\n"
            "3. Do not present a move that happened alongside something as caused by it. State a cause only when a credible source you "
            "found states it, and say who; otherwise write 'as' or 'while', or leave the cause out.\n\n"
            f"Already covered recently, do not repeat these subjects: {'; '.join(covered[-25:]) or 'none'}.\n\n"
            "Write the post to the brief: a hook of at most 140 characters and a body of 105 to 140 words that connects three things, in "
            "this order: WHAT HAPPENED in the real world, with its figures; WHY it happened, from a business, financial or management "
            "view; and WHAT a CEO, CFO, COO or business owner should learn or do differently. Add ONE line of the author's view as a "
            "finance and operations leader, then one closing question. Do not invent a personal anecdote, a place he was or anything he did. "
            "No investment advice: never say to buy, sell or hold, and no price forecast. No em-dashes, no emojis.\n\n"
            f"THE FIRST LINE decides everything: it is all a reader sees before 'see more'. Write {HOOKS} different openings in \"hooks\", "
            "each at most 140 characters, each true to your claims and using no number that is not in a claim: one that opens on the "
            "surprising figure, one on the named company or person doing something, one that takes a side a reader may want to argue "
            "with, one as a question a manager has actually asked, and the rest your best. No 'Here is why', no 'Let that sink in', "
            "no lecture. Put your own favourite in \"hook\" as well. End the post on a question that has two defensible answers, so a "
            "reader can reply in one line with a view of their own; never 'What do you think?' or 'Agree?'."
            f"{lessons}\n\n"
            "Reply with JSON only, exactly this shape:\n"
            '{"id": "short-kebab-id", "hook": "...", "hooks": ["...", "..."], "body": "...", "question": "...?", "hashtags": ["#A", "#B", "#C"], '
            '"card": {"title": "at most 60 characters", "points": ["at most 70 characters each, 3 to 5 points"], "source": "the main sources, short"}, '
            '"scene": "one photorealistic scene for the picture: a place or object, no text, no logos, no real person", '
            '"visual": {"format": "photo | chart | infographic | comparison", "why": "one sentence: why this format tells the story best", '
            '"chart": "bar | line | donut | waterfall | timeline | process | map | kpi (omit for a photo)", "title": "the one insight, at most 60 characters", '
            '"data": [{"label": "...", "value": 0, "unit": "% or USD bn or ..."}], "period": "what period and date the data covers", '
            '"source": "the original data source, short", "highlight": "the one value to draw the eye to"}, '
            '"as_of": "YYYY-MM-DD, the date of the latest figure in the post", '
            '"claims": [{"claim": "one checkable statement exactly as the post makes it, with its figures", "sources": ["url", "url"]}]}\n'
            f"At most {MAX_CLAIMS} claims: build the post on a few solid facts, and state each claim in one plain sentence so that a second "
            "reader can confirm it with one search. "
            "Every number in the hook, the body, the card and the visual's data must appear in a claim, and every source must be a page "
            "your search returned.\n\n"
            "The visual (his brief, the data visualisation rules): do not default to a photograph. Choose a chart, an infographic or a "
            "comparison when the story is in the numbers (bars for comparisons, a line for a history, a donut for a composition whose "
            "parts total 100 percent, a waterfall for a bridge, a timeline for a sequence), and a photograph when it is not. Use a data "
            "visual ONLY with actual, verified figures of one period and one definition, each of them in your claims; never estimate a "
            "missing value, never mix actuals with forecasts unmarked. If the reliable data is too thin for a chart, choose the photograph.")


def repair_prompt(problems: list) -> str:
    return ("That post did not pass these checks:\n- " + "\n- ".join(problems[:8]) +
            "\n\nMend exactly these and change nothing else that is sound. For a claim without two sources on DIFFERENT sites: search again "
            "and add a second site that confirms it, or remove the claim AND the sentence that makes it. Every number in the hook, body and "
            "card, years included, must appear in a claim. A source must be a page your search returned. Keep the body at 105 to 140 words. "
            "Reply with the whole JSON again, same shape.")


def gate(post: dict, urls: set, category: str, day: date, settings: dict) -> list:
    """Checks 1 to 5. A non-empty result means: do not post this."""
    from . import linkedin_personal as lp
    problems = []
    claims = post.get("claims") or []
    if not claims:
        problems.append("no claims listed")
    if len(claims) > MAX_CLAIMS:
        problems.append(f"{len(claims)} claims: keep the post to at most {MAX_CLAIMS} checkable facts")
    for c in claims:
        srcs = [s for s in (c.get("sources") or []) if isinstance(s, str)]
        unseen = [s for s in srcs if s not in urls]
        if unseen:
            problems.append(f"a source the search did not return: {unseen[0][:80]}")
        if len({_site(s) for s in srcs if s in urls}) < 2:
            problems.append(f"fewer than two sites back: {str(c.get('claim'))[:70]}")
    card = post.get("card") or {}
    shown = " ".join([str(post.get("hook", "")), str(post.get("body", "")), str(card.get("title", "")), " ".join(card.get("points") or [])])
    visual = post.get("visual") or {}
    data = visual.get("data") or []
    if str(visual.get("format") or "photo") != "photo":
        if len(data) < 2:
            problems.append("a data visual needs at least two verified data points; use a photograph instead")
        if not visual.get("period") or not visual.get("source"):
            problems.append("a data visual needs its period and its source")
        if visual.get("chart") == "donut":
            try:
                total = sum(float(d.get("value")) for d in data)
            except (TypeError, ValueError):
                total = 0
            if abs(total - 100) > 0.5:
                problems.append(f"the donut's parts total {total:g}, not 100")
        shown += " " + " ".join(f"{d.get('value')}" for d in data) + " " + str(visual.get("title") or "")
    missing = _numbers(shown) - _numbers(" ".join(str(c.get("claim", "")) for c in claims))
    if missing:
        problems.append(f"numbers in the post that no claim covers: {', '.join(sorted(missing)[:6])}")
    if category in FRESH:
        try:
            age = (day - date.fromisoformat(str(post.get("as_of")))).days
        except ValueError:
            age = None
        if age is None or not 0 <= age <= FRESH[category]:
            problems.append(f"the {'market figures are' if category == 'markets' else 'story is'} dated {post.get('as_of')!r}, not within {FRESH[category]} days")
    item = to_item(post, category)
    return problems + lp.lint_personal(item, settings)


def to_item(post: dict, category: str) -> dict:
    claims = post.get("claims") or []
    facts = "; ".join(f"{c.get('claim')} [{', '.join(_site(s) for s in c.get('sources') or [])}]" for c in claims)[:1500]
    return {"id": f"live-{str(post.get('id') or category)[:40]}", "pillar": category, "hook": str(post.get("hook", "")).strip(),
            "body": str(post.get("body", "")).strip(), "question": str(post.get("question", "")).strip(),
            "hashtags": [h for h in post.get("hashtags") or [] if isinstance(h, str)][:4], "card": post.get("card") or {},
            "scene": str(post.get("scene") or ""), "visual": post.get("visual") or {}, "facts": facts or "", "as_of": post.get("as_of"),
            "sources": sorted({s for c in claims for s in c.get("sources") or []})[:8]}


def verify_prompt(post: dict, day: date) -> str:
    claims = [c.get("claim") for c in post.get("claims") or []]
    return (f"Today is {day:%d %B %Y}. A post is about to be published under a finance executive's name. Check each claim below "
            "against the web yourself; do not trust the claim's wording. A claim is true only if you find it confirmed, with its figures "
            "and dates, by a credible source. Also say whether the hook is supported by the facts. Spend your searches evenly: one or two "
            "per claim, and never leave a claim unchecked. If you could not check a claim, mark it false and say so in the note.\n\n"
            "Then read the post itself and answer four more questions strictly. sources_credible: does every market figure rest on a "
            "primary or highly credible source? expectations_clear: is everything that is only expected (futures pricing, forecasts, a "
            "bank's call) worded as an expectation, never as a decision taken? causes_supported: is every 'because' or cause in the post "
            "stated by a credible source, with nothing that merely happened alongside presented as the cause? three_parts: does the post "
            "say what happened, why it happened, and what a business leader should learn or do?\n\n"
            f"Hook: {post.get('hook')}\nPost: {post.get('body')}\nClaims:\n" + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(claims)) +
            '\n\nReply with JSON only: {"claims": [{"n": 1, "true": true, "note": "short"}], "hook_supported": true, '
            '"sources_credible": true, "expectations_clear": true, "causes_supported": true, "three_parts": true, "note": "short, if any is false"}')


def best_hook(post: dict, ask=call) -> str:
    """The hook tournament (founder, 25 Nov 2026: the steps the video channels got, for LinkedIn). The writer's openings that are
    short enough and use only proven numbers go before a panel of three readers; the best scored one opens the post. Anything going
    wrong leaves the writer's own hook in place."""
    own = str(post.get("hook", "")).strip()
    proven = _numbers(" ".join(str(c.get("claim", "")) for c in post.get("claims") or []))
    lines = []
    for h in [own] + [str(h).strip() for h in post.get("hooks") or [] if isinstance(h, str)]:
        if h and h not in lines and len(h) <= 140 and "—" not in h and _numbers(h) <= proven:
            lines.append(h)
    if len(lines) < 2:
        return own
    try:
        rows = _json(ask([{"role": "user", "content": PANEL + "\n".join(f"{i + 1}. {h}" for i, h in enumerate(lines))}],
                         "You score opening lines honestly.", searches=0)["text"]).get("scores") or []
        totals = [sum(float(x) for x in r) for r in rows]
        if len(totals) != len(lines):
            return own
        return lines[max(range(len(lines)), key=lambda i: totals[i])]
    except (LiveError, ValueError, TypeError, KeyError, OSError):
        return own


def _lessons(root: Path) -> str:
    try:
        from . import linkedin_review
        return linkedin_review.lesson_text(root)
    except Exception:                                         # noqa: BLE001  a broken lessons file never stops a post
        return ""


def write(category: str, day: date, covered: list, settings: dict, *, root: Path = ROOT, ask=call):
    """(post ready for the lane, "") or (None, why not). Never raises: the caller falls back to the bank."""
    try:
        system = (Path(root) / BRIEF).read_text()
        prompt = write_prompt(category, day, covered, _lessons(root))
        first = ask([{"role": "user", "content": prompt}], system)
        post, urls = _json(first["text"]), set(first["urls"])
        problems = gate(post, urls, category, day, settings)
        if problems:
            # 21 Nov 2026, the first real run: a sound post failed on one claim with a single site and one year no claim covered.
            # The checks stay as strict; the writer gets one chance to mend exactly what failed, then the bank post goes out.
            again = ask([{"role": "user", "content": prompt}, {"role": "assistant", "content": first["text"]},
                         {"role": "user", "content": repair_prompt(problems)}], system)
            post, urls = _json(again["text"]), urls | set(again["urls"])
            problems = gate(post, urls, category, day, settings)
        if problems:
            return None, "; ".join(problems[:3])
        chosen = best_hook(post, ask)
        if chosen != post.get("hook") and not gate({**post, "hook": chosen}, urls, category, day, settings):
            post["hook"] = chosen                             # the second check below judges the hook that goes out
        check = _json(ask([{"role": "user", "content": verify_prompt(post, day)}],
                          "You are a careful fact checker. Search before you answer.", searches=CHECK_SEARCHES)["text"])
        rows = check.get("claims") or []
        bad = [r for r in rows if r.get("true") is not True]
        if len(rows) < len(post["claims"]) or bad or check.get("hook_supported") is not True:
            why = (bad[0].get("note") if bad else "") or "the hook is not supported, or a claim was left unchecked"
            return None, f"the second check did not confirm it: {str(why)[:160]}"
        failed = [k for k in QUALITY if check.get(k) is not True]
        if failed:
            return None, f"the second check found: {', '.join(QUALITY[k] for k in failed)} ({str(check.get('note') or '')[:120]})"
        return to_item(post, category), ""
    except (LiveError, OSError, KeyError, TypeError) as e:
        return None, f"{type(e).__name__}: {str(e)[:160]}"
