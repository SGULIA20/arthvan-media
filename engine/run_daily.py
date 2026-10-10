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

from . import instagram, linkedin, render
from .config import ROOT, load_apps, load_bank
from .instagram import Captions, InstagramError, PartialPublish, SetUrls
from .lint import alt_texts, build_captions, build_linkedin_text, lint_item
from .linkedin import LinkedInError
from .select_item import lagos_date, pick

MAX_FALLBACKS = 5
KEEP_DAYS = 14
DEFAULT_REPO = "SGULIA20/arthvan-media"


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


def _do_linkedin(day: date, app_cfg: dict, item: dict, slides: list, deps: Deps, log: Path, token: str, urn: str) -> bool:
    text, tags = build_linkedin_text(app_cfg, item)
    entry = {"date": day.isoformat(), "channel": "linkedin", "item": item["id"]}
    try:
        post_urn = deps.post_linkedin(token, urn, text, tags, slides, alt_texts(app_cfg, item))
    except LinkedInError as e:
        _append(log, dict(entry, status="failed", error=str(e)[:300]))
        deps.git_publish([log], f"log: linkedin failed {day}")
        print(f"LinkedIn failed: {e}")
        return False
    _append(log, dict(entry, status="published", id=post_urn))
    deps.git_publish([log], f"log: linkedin published {day}")
    print(f"LinkedIn published {post_urn}")
    return True


def _linkedin_retry(day: date, root: Path, log: Path, apps: dict, banks: dict, deps: Deps, token: str, urn: str) -> int:
    """Instagram already went out today; only LinkedIn is missing."""
    rows = [e for e in _entries(log) if e.get("date") == day.isoformat() and e.get("status") == "published"
            and e.get("channel", "instagram") == "instagram"]
    item = next((i for i in banks.get(rows[-1]["app"], []) if i["id"] == rows[-1]["item"]), None) if rows else None
    slides = sorted((root / "out" / day.isoformat()).glob("slide_*.jpg"), key=lambda p: int(p.stem.split("_")[1]))
    if item is None or not slides:
        print("cannot retry LinkedIn: today's item or slides are missing")
        return 1
    return 0 if _do_linkedin(day, apps[rows[-1]["app"]], item, slides, deps, log, token, urn) else 1


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
    li_token, li_urn = env.get("LINKEDIN_ACCESS_TOKEN"), env.get("LINKEDIN_PERSON_URN")
    li_on = bool(li_token and li_urn)
    if mode == "post":
        deps.sync_repo()
        status = day_status(log, day)
        if status == "published":
            if li_on and day_status(log, day, "linkedin") != "published":
                return _linkedin_retry(day, root, log, apps, banks, deps, li_token, li_urn)
            print(f"{day} already posted: nothing to do")
            return 0
        if status is not None:
            print(f"{day}: an earlier run stopped at '{status}'. Check Instagram by hand; nothing was posted again.")
            return 1

    sel = None
    for skip in range(MAX_FALLBACKS):
        cand = pick(day, banks, skip=skip)
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

        entry = {"date": day.isoformat(), "app": sel.app, "item": sel.item["id"], "status": "publishing",
                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
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
        if li_on:
            return 0 if _do_linkedin(day, apps[sel.app], sel.item, rs.slides, deps, log, li_token, li_urn) else 1
        return 0
    except (TimeoutError, InstagramError, subprocess.CalledProcessError) as e:
        print(f"run failed: {type(e).__name__}: {e}")
        return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("render", "prepare", "post"), default="render")
    ap.add_argument("--date", help="YYYY-MM-DD (Lagos date); default: today in Lagos")
    args = ap.parse_args(argv)
    day = date.fromisoformat(args.date) if args.date else lagos_date(datetime.now(timezone.utc))
    return run(args.mode, day)


if __name__ == "__main__":
    sys.exit(main())
