"""Daily orchestrator: select, lint, render, publish media, prepare Instagram containers, publish.

python -m engine.run_daily --mode render|prepare|post [--date YYYY-MM-DD]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import instagram, linkedin, notify, render, telegram, threads, whatsapp, youtube
from .config import ROOT, load_apps, load_bank, load_global
from .instagram import Captions, InstagramError, PartialPublish, SetUrls
from .lint import alt_texts, build_captions, build_linkedin_text, build_threads_text, lint_item, story_captions
from .linkedin import LinkedInError
from .threads import ThreadsError
from .youtube import YouTubeError
from .whatsapp import WhatsAppError, WhatsAppNotReady
from . import claims
from .calendar_plan import load_schedule, load_stories, planned_features
from .select_item import ORDER, EPOCH, lagos_date, pick, slot, story_lead, NO_REPEAT_DAYS

MAX_FALLBACKS = 5
WA_MAX_BYTES = 15 * 1024 * 1024   # WhatsApp rejects template videos above 16 MB
KEEP_DAYS = 14
DEFAULT_REPO = "SGULIA20/arthvan-media"
YT_CHANNELS = ("sglearning", "arthvan")   # every Short goes to both channels


# ---------- real implementations of the side effects ----------
def http_size(url: str):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "arthvan-autoposter"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("Content-Length", -1))
    except Exception:
        return None


def wait_for_urls(expected: dict, timeout_s: float = 600, fetch=http_size, sleep=time.sleep,
                  clock=time.monotonic, poll_s: float = 10) -> None:
    """Block until every URL answers with the expected byte size, else raise TimeoutError."""
    start = clock()
    pending = dict(expected)
    while True:
        pending = {u: s for u, s in pending.items() if fetch(u) != s}
        if not pending:
            return
        if clock() - start > timeout_s:
            raise TimeoutError(f"not live after {timeout_s}s: {sorted(pending)}")
        sleep(poll_s)


def git_publish(paths: list, message: str) -> None:
    subprocess.run(["git", "add", "-A", *map(str, paths)], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)


def sync_repo() -> None:
    """In CI, take the newest main so a re-run sees the log written by the run it repeats."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        subprocess.run(["git", "pull", "--ff-only", "origin", "main"], check=True)


def head_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


@dataclass
class Deps:
    render_set: Callable = render.render_set
    verify_set: Callable = render.verify_set
    git_publish: Callable = git_publish
    wait_for_urls: Callable = wait_for_urls
    prepare_set: Callable = instagram.prepare_set
    publish_set: Callable = instagram.publish_set
    sync_repo: Callable = sync_repo
    head_sha: Callable = head_sha
    post_linkedin: Callable = linkedin.post_set
    post_threads: Callable = threads.post_carousel
    post_threads_video: Callable = threads.post_video
    send_telegram: Callable = telegram.send_video
    prepare_video_set: Callable = instagram.prepare_video_set
    post_linkedin_video: Callable = linkedin.post_video
    post_youtube: Callable = youtube.post_short
    send_whatsapp: Callable = whatsapp.send_status_video


# ---------- helpers ----------
def _entries(log: Path):
    if not log.exists():
        return
    for line in log.read_text().splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def day_status(log: Path, day: date, channel: str = "instagram"):
    """Latest recorded status for the day on a channel: publishing, published, partial, or None."""
    last = None
    for e in _entries(log):
        if (e.get("date") == day.isoformat() and e.get("channel", "instagram") == channel
                and e.get("status") in ("publishing", "published", "partial")):
            last = e["status"]
    return last


def already_posted(log: Path, day: date) -> bool:
    return day_status(log, day) is not None


def _append(log: Path, entry: dict) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def prune_old(out_root: Path, today: date, keep_days: int = KEEP_DAYS) -> None:
    if not out_root.exists():
        return
    for d in out_root.iterdir():
        try:
            folder_day = date.fromisoformat(d.name)
        except ValueError:
            continue
        if folder_day < today - timedelta(days=keep_days):
            shutil.rmtree(d)


def _channel(day: date, channel: str, item_id: str, deps: Deps, log: Path, action) -> bool:
    """Run one extra channel; its failure is logged and isolated, never affecting Instagram."""
    entry = {"date": day.isoformat(), "channel": channel, "item": item_id}
    try:
        post_id = action()
    except WhatsAppNotReady as e:
        _append(log, dict(entry, status="waiting", note=str(e)[:300]))
        deps.git_publish([log], f"log: {channel} waiting {day}")
        print(f"{channel} waiting: {e}")
        return True
    except (LinkedInError, ThreadsError, YouTubeError, WhatsAppError, telegram.TelegramError) as e:
        _append(log, dict(entry, status="failed", error=str(e)[:300]))
        deps.git_publish([log], f"log: {channel} failed {day}")
        print(f"{channel} failed: {e}")
        return False
    _append(log, dict(entry, status="published", id=post_id))
    deps.git_publish([log], f"log: {channel} published {day}")
    print(f"{channel} published {post_id}")
    return True


def _do_linkedin(day, app_cfg, item, slides, deps, log, token, urn) -> bool:
    text, tags = build_linkedin_text(app_cfg, item)
    return _channel(day, "linkedin", item["id"], deps, log,
                    lambda: deps.post_linkedin(token, urn, text, tags, slides, alt_texts(app_cfg, item)))


def _do_threads(day, app_cfg, item, slide_urls, deps, log, token, uid) -> bool:
    return _channel(day, "threads", item["id"], deps, log,
                    lambda: deps.post_threads(uid, token, slide_urls, build_threads_text(app_cfg, item)))


def _do_youtube(day, app_cfg, item, video_path, deps, log, channels: dict, title, desc) -> bool:
    """One upload per configured channel; each channel has its own log line and retries on its own."""
    ok = True
    for name, channel in channels.items():
        if day_status(log, day, f"youtube:{name}") == "published":
            continue
        ok &= _channel(day, f"youtube:{name}", item["id"], deps, log,
                       lambda c=channel: deps.post_youtube(c, video_path, title, desc, app_cfg["play_url"],
                                                           [t.lstrip("#") for t in item.get("hashtags", [])] + app_cfg["base_hashtags"]))
    return ok


def _extras(day, app_cfg, item, slides, slide_urls, deps, log, chans) -> int:
    """Post to every enabled extra channel that has not succeeded today. Returns 0 when all are fine."""
    ok = True
    wa = chans.get("whatsapp")
    if wa and day_status(log, day, "whatsapp") != "published" and slide_urls:
        reel_url = slide_urls[0].rsplit("/", 1)[0] + "/reel.mp4"
        caption = (item["slides"][0]["text"] if item.get("slides") else item["caption"][:120]) + " " + app_cfg["play_url"]
        ok &= _channel(day, "whatsapp", item["id"], deps, log, lambda: deps.send_whatsapp(wa, reel_url, app_cfg["name"], caption))
    tg = chans.get("telegram")
    if tg and day_status(log, day, "telegram") != "published" and slide_urls:
        reel_url = slide_urls[0].rsplit("/", 1)[0] + "/reel.mp4"
        caption = (item["slides"][0]["text"] if item.get("slides") else item["caption"][:120]) + " " + app_cfg["play_url"]
        ok &= _channel(day, "telegram", item["id"], deps, log, lambda: deps.send_telegram(tg, reel_url, caption))
    yt = chans.get("youtube", {})
    if yt and slides:
        video = Path(slides[0]).parent / "reel.mp4"
        if video.exists():
            title = item["slides"][0]["text"] if item.get("slides") else item["caption"][:80]
            ok &= _do_youtube(day, app_cfg, item, video, deps, log, yt, title, item["caption"])
    if chans.get("threads") and day_status(log, day, "threads") != "published":
        ok &= _do_threads(day, app_cfg, item, slide_urls, deps, log, *chans["threads"])
    if chans.get("linkedin") and day_status(log, day, "linkedin") != "published":
        ok &= _do_linkedin(day, app_cfg, item, slides, deps, log, *chans["linkedin"])
    return 0 if ok else 1


def _extras_retry(day, root, log, apps, banks, deps, chans, env) -> int:
    """Instagram already went out today; only an extra channel is missing."""
    rows = [e for e in _entries(log) if e.get("date") == day.isoformat() and e.get("status") == "published"
            and e.get("channel", "instagram") == "instagram"]
    if rows and rows[-1].get("kind") == "story":
        return _story_retry(rows[-1], day, root, log, apps, deps, chans, env)
    item = next((i for i in banks.get(rows[-1]["app"], []) if i["id"] == rows[-1]["item"]), None) if rows else None
    slides = sorted((root / "out" / day.isoformat()).glob("slide_*.jpg"), key=lambda p: int(p.stem.split("_")[1]))
    if item is None or not slides:
        print("cannot retry: today's item or slides are missing")
        return 1
    sha = rows[-1].get("sha") or deps.head_sha()
    base = f"https://raw.githubusercontent.com/{env.get('GITHUB_REPOSITORY', DEFAULT_REPO)}/{sha}/out/{day.isoformat()}"
    return _extras(day, apps[rows[-1]["app"]], item, slides, [f"{base}/{p.name}" for p in slides], deps, log, chans)


def scheduled_story(root: Path, day: date, log: Path = None):
    """The earliest story that fits today's slot (app and lead, see select_item.slot), whose post_on is today or
    earlier (post_on means "not before"), has a rendered MP4 in stories/out/ and has not been published yet.
    A story missed while posting was down goes out on the next day with a matching slot."""
    done = set()
    if log is not None:
        for e in _entries(log):
            if e.get("status") == "published" and e.get("channel", "instagram") == "instagram":
                done.add(e.get("item"))
    sched = load_schedule(root)
    if sched is not None:                       # a planned calendar (engine.calendar_plan) decides which Reel goes out, and when
        by_id = {s["id"]: s for s in load_stories(root)}
        today = by_id.get(sched.get(day.isoformat()))
        if today and today["rendered"] and today["id"] not in done and not today["problems"]:
            return today                                                    # today's own Reel comes first
        for d in sorted(sched):                                             # else one missed in the last 3 days
            st = by_id.get(sched[d])
            if st and st["rendered"] and not st["problems"] and st["id"] not in done and (day - timedelta(days=3)).isoformat() < d < day.isoformat():
                return st
        return None
    cands = []
    for p in sorted((root / "stories").glob("*.json")):
        try:
            st = json.loads(p.read_text())
        except ValueError:
            continue
        rendered = (root / "stories" / "out" / f"{st['id']}.mp4").exists() and not claims.story_problems(st, *claims.load(root))
        if st.get("occasion") and st.get("post_on") == day.isoformat() and st["id"] not in done and rendered:
            return st                                   # a festival or national day wins its date, whatever the cycle says
        if (st.get("post_on") and st["post_on"] <= day.isoformat() and st["id"] not in done
                and (st["app"], story_lead(st)) == slot(day) and rendered):
            cands.append(st)
    if not cands:
        return None
    avoid = set(recent_features(log, cands[0]["app"], day))
    fresh = [c for c in cands if c.get("feature") not in avoid]
    return min(fresh or cands, key=lambda s: s["post_on"])


def recent_features(log: Path, app: str, day: date, days: int = NO_REPEAT_DAYS) -> list:
    """Features the app published on Instagram in the `days` days before `day`, oldest first (bank items and stories alike)."""
    if log is None or not log.exists():
        return []
    since = (day - timedelta(days=days)).isoformat()
    feats = []
    for e in _entries(log):
        if (e.get("status") == "published" and e.get("channel", "instagram") == "instagram" and e.get("app") == app
                and e.get("feature") and since <= e.get("date", "") < day.isoformat()):
            feats.append(e["feature"])
    return feats


def _story_extras(st, day, app_cfg, dst, url, deps, log, chans, li_text, tags) -> bool:
    """Every extra channel for a story day: WhatsApp status video, YouTube (both channels), LinkedIn video, Threads video.
    Each is skipped when it already succeeded today, so this is also the retry."""
    ok = True
    wa = chans.get("whatsapp")
    if wa and dst.stat().st_size > WA_MAX_BYTES:
        print(f"whatsapp skipped: {dst.stat().st_size / 1048576:.1f} MB is over WhatsApp's 16 MB video limit")
        wa = None
    if wa and day_status(log, day, "whatsapp") != "published":
        ok &= _channel(day, "whatsapp", st["id"], deps, log, lambda: deps.send_whatsapp(wa, url, app_cfg["name"], st["caption"] + " " + app_cfg["play_url"]))
    tg = chans.get("telegram")
    if tg and day_status(log, day, "telegram") != "published":
        ok &= _channel(day, "telegram", st["id"], deps, log, lambda: deps.send_telegram(tg, url, st["caption"] + " " + app_cfg["play_url"]))
    yt = chans.get("youtube", {})
    if yt:
        ok &= _do_youtube(day, app_cfg, st, dst, deps, log, yt, st.get("title", app_cfg["name"]), st["caption"])
    if chans.get("linkedin_any") and day_status(log, day, "linkedin") != "published":
        tok, urn = chans["linkedin_any"]
        ok &= _channel(day, "linkedin", st["id"], deps, log,
                       lambda: deps.post_linkedin_video(tok, urn, li_text, tags, dst, st.get("title", app_cfg["name"])))
    if chans.get("threads") and day_status(log, day, "threads") != "published":
        th_token, th_uid = chans["threads"]
        text = build_threads_text(app_cfg, {"caption": st["caption"], "hashtags": st.get("hashtags", []), "slides": []})
        ok &= _channel(day, "threads", st["id"], deps, log, lambda: deps.post_threads_video(th_uid, th_token, url, text))
    return ok


def _story_retry(row, day, root, log, apps, deps, chans, env) -> int:
    """A story went out on Instagram earlier today; post the channels that are still missing."""
    st = next((s for s in load_stories(root) if s["id"] == row["item"]), None)
    if st is None:
        print("cannot retry: today's story file is missing"); return 1
    app_cfg = apps[st["app"]]
    dst = root / "out" / day.isoformat() / "story.mp4"
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(root / "stories" / "out" / f"{st['id']}.mp4", dst)
    repo = env.get("GITHUB_REPOSITORY", DEFAULT_REPO)
    url = f"https://raw.githubusercontent.com/{repo}/{row.get('sha') or deps.head_sha()}/out/{day.isoformat()}/story.mp4"
    _, li_text, tags = story_captions(app_cfg, st)
    return 0 if _story_extras(st, day, app_cfg, dst, url, deps, log, chans, li_text, tags) else 1


def _run_story(st: dict, day: date, root: Path, env, deps: Deps, apps: dict, log: Path, chans: dict, token: str, ig_id: str, mode: str) -> int:
    app_cfg = apps[st["app"]]
    src = root / "stories" / "out" / f"{st['id']}.mp4"
    out_dir = root / "out" / day.isoformat(); out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "story.mp4"; shutil.copy(src, dst)
    print(f"story day: {st['id']} ({st['app']})")
    if mode == "render":
        return 0
    try:
        prune_old(root / "out", day)
        deps.git_publish([root / "out"], f"story media for {day}")
        repo = env.get("GITHUB_REPOSITORY", DEFAULT_REPO)
        url = f"https://raw.githubusercontent.com/{repo}/{deps.head_sha()}/out/{day.isoformat()}/story.mp4"
        deps.wait_for_urls({url: dst.stat().st_size})
        ig_caption, li_text, tags = story_captions(app_cfg, st)
        prepared = deps.prepare_video_set(ig_id, token, url, ig_caption)
        if mode == "prepare":
            return 0
        entry = {"date": day.isoformat(), "app": st["app"], "item": st["id"], "status": "publishing", "kind": "story", "feature": st.get("feature"),
                 "sha": deps.head_sha(), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _append(log, entry); deps.git_publish([log], f"log: publishing {day}")
        try:
            ids = deps.publish_set(ig_id, token, prepared)
        except PartialPublish as e:
            _append(log, dict(entry, status="partial", ids=e.ids)); deps.git_publish([log], f"log: partial publish {day}")
            print(f"run failed: {e}"); return 1
        _append(log, dict(entry, status="published", ids=ids)); deps.git_publish([log], f"log: published {day}")
        print(f"published story {st['id']}: {ids}")
        ok = _story_extras(st, day, app_cfg, dst, url, deps, log, chans, li_text, tags)
        return 0 if ok else 1
    except (TimeoutError, InstagramError, subprocess.CalledProcessError) as e:
        print(f"run failed: {type(e).__name__}: {e}"); return 1


# ---------- the run ----------
def run(mode: str, day: date, *, root: Path = ROOT, env=None, deps: Deps = None, banks=None, apps=None) -> int:
    env = os.environ if env is None else env
    deps = deps or Deps()
    if env.get("PAUSE") == "1" or (root / "PAUSE").exists():
        print("paused: nothing to do")
        return 0
    token, ig_id = env.get("IG_ACCESS_TOKEN"), env.get("IG_USER_ID")
    if mode in ("prepare", "post") and not (token and ig_id):
        print("IG_ACCESS_TOKEN and IG_USER_ID must be set")
        return 1
    log = root / "logs" / "posts.jsonl"
    apps = apps or load_apps()
    banks = banks or {a: load_bank(a) for a in apps}
    _feats, _smap = claims.load(root)
    banks = {a: [i for i in b if not claims.item_problems(a, i, _feats)] or b for a, b in banks.items()}   # nothing false or premature is picked
    chans = {}
    li_token, li_urn = env.get("LINKEDIN_ACCESS_TOKEN"), env.get("LINKEDIN_PERSON_URN")
    # LinkedIn gets one post a week, on the day set in content/apps.json (Tuesday)
    if li_token and li_urn and day.weekday() == load_global().get("linkedin_weekday", 1):
        chans["linkedin"] = (li_token, li_urn)
    if li_token and li_urn:
        chans["linkedin_any"] = (li_token, li_urn)   # story ads go to LinkedIn whatever the weekday
    th_token, th_uid = env.get("THREADS_ACCESS_TOKEN"), env.get("THREADS_USER_ID")
    if th_token and th_uid:
        chans["threads"] = (th_token, th_uid)
    if all(env.get(k) for k in ("GUPSHUP_APP_ID", "GUPSHUP_API_KEY", "WA_STATUS_TO", "WA_STATUS_TEMPLATE")):
        chans["whatsapp"] = {"app_id": env["GUPSHUP_APP_ID"], "api_key": env["GUPSHUP_API_KEY"].strip(),
                             "app_name": env.get("GUPSHUP_APP_NAME") or "scoremybizapp",
                             "source": env.get("GUPSHUP_SOURCE") or "2348125666665",
                             "to": env["WA_STATUS_TO"], "template": env["WA_STATUS_TEMPLATE"]}
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        chans["telegram"] = {"token": env["TELEGRAM_BOT_TOKEN"].strip(), "chat_id": env["TELEGRAM_CHAT_ID"].strip()}
    chans["youtube"] = {ch: {"client_id": env["YT_CLIENT_ID"], "client_secret": env["YT_CLIENT_SECRET"],
                             "refresh_token": env[f"YT_{ch.upper()}_REFRESH_TOKEN"]}
                        for ch in YT_CHANNELS if env.get("YT_CLIENT_ID") and env.get("YT_CLIENT_SECRET") and env.get(f"YT_{ch.upper()}_REFRESH_TOKEN")}
    if mode == "post":
        deps.sync_repo()
        status = day_status(log, day)
        if status == "published":
            missing = [c for c in chans if c not in ("linkedin_any", "youtube") and day_status(log, day, c) != "published"] + [f"youtube:{n}" for n in chans.get("youtube", {}) if day_status(log, day, f"youtube:{n}") != "published"]
            if missing:
                return _extras_retry(day, root, log, apps, banks, deps, chans, env)
            print(f"{day} already posted: nothing to do")
            return 0
        if status is not None:
            print(f"{day}: an earlier run stopped at '{status}'. Check Instagram by hand; nothing was posted again.")
            return 1

    story = scheduled_story(root, day, log)
    if story is not None:
        if mode == "post" and day_status(log, day) is not None:
            missing = [c for c in chans if c not in ("linkedin_any", "youtube") and day_status(log, day, c) != "published"] + [f"youtube:{n}" for n in chans.get("youtube", {}) if day_status(log, day, f"youtube:{n}") != "published"]
            print(f"{day} story already posted")
            return 0
        return _run_story(story, day, root, env, deps, apps, log, chans, token, ig_id, mode)
    sel = None
    for skip in range(MAX_FALLBACKS):
        cand = pick(day, banks, skip=skip, recent_features=recent_features(log, ORDER[(day - EPOCH).days % 2], day) + planned_features(root, ORDER[(day - EPOCH).days % 2], day))
        problems = lint_item(apps[cand.app], cand.item)
        if not problems:
            sel = cand
            break
        print(f"lint rejected {cand.item['id']}: {problems}")
    if sel is None:
        print(f"all {MAX_FALLBACKS} candidate items failed lint")
        return 1

    out_root = root / "out"
    out_dir = out_root / day.isoformat()
    try:
        rs = deps.render_set(sel, apps[sel.app], out_dir)
        problems = deps.verify_set(rs)
        if problems:
            print(f"render check failed: {problems}")
            return 1
        print(f"rendered {sel.item['id']} ({sel.app}), {rs.seconds:.1f}s reel")
        if mode == "render":
            return 0

        prune_old(out_root, day)
        deps.git_publish([out_root], f"media for {day}")
        repo = env.get("GITHUB_REPOSITORY", DEFAULT_REPO)
        base = f"https://raw.githubusercontent.com/{repo}/{deps.head_sha()}/out/{day.isoformat()}"
        urls = SetUrls(slides=[f"{base}/{p.name}" for p in rs.slides], reel=f"{base}/{rs.reel.name}",
                       story=f"{base}/{rs.story.name}")
        expected = {u: p.stat().st_size for u, p in zip(urls.slides, rs.slides)}
        expected[urls.reel] = rs.reel.stat().st_size
        expected[urls.story] = rs.story.stat().st_size
        deps.wait_for_urls(expected)

        post_cap, reel_cap = build_captions(apps[sel.app], sel.item)
        prepared = deps.prepare_set(ig_id, token, urls, Captions(post=post_cap, reel=reel_cap))
        print("all containers ready")
        if mode == "prepare":
            return 0

        entry = {"date": day.isoformat(), "app": sel.app, "item": sel.item["id"], "status": "publishing", "feature": sel.item.get("feature"),
                 "sha": deps.head_sha(), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _append(log, entry)
        deps.git_publish([log], f"log: publishing {day}")
        try:
            ids = deps.publish_set(ig_id, token, prepared)
        except PartialPublish as e:
            _append(log, dict(entry, status="partial", ids=e.ids))
            deps.git_publish([log], f"log: partial publish {day}")
            print(f"run failed: {e}")
            return 1
        _append(log, dict(entry, status="published", ids=ids))
        deps.git_publish([log], f"log: published {day}")
        print(f"published {sel.item['id']}: {ids}")
        return _extras(day, apps[sel.app], sel.item, rs.slides, urls.slides, deps, log, chans)
    except (TimeoutError, InstagramError, subprocess.CalledProcessError) as e:
        print(f"run failed: {type(e).__name__}: {e}")
        return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("render", "prepare", "post"), default="render")
    ap.add_argument("--date", help="YYYY-MM-DD (Lagos date); default: today in Lagos")
    args = ap.parse_args(argv)
    day = date.fromisoformat(args.date) if args.date else lagos_date(datetime.now(timezone.utc))
    if args.mode != "post":
        return run(args.mode, day)
    before = len(notify.entries(ROOT / "logs" / "posts.jsonl"))
    try:
        code = run(args.mode, day)
    except Exception:
        notify.after_run(ROOT, day, 1, before)         # a crash still reaches the founder; the traceback is in the GitHub run
        raise
    notify.after_run(ROOT, day, code, before)          # failure -> alert, something posted -> summary, nothing to do -> silence
    return code


if __name__ == "__main__":
    sys.exit(main())
