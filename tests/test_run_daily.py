import json
from datetime import date
from pathlib import Path

import pytest

from engine.instagram import PartialPublish, Prepared
from engine.linkedin import LinkedInError
from engine.threads import ThreadsError
from engine.youtube import YouTubeError
from engine.render import RenderedSet
from engine.run_daily import Deps, already_posted, prune_old, run, wait_for_urls

DAY = date(2026, 10, 11)  # waypoint day
ENV = {"IG_ACCESS_TOKEN": "tok", "IG_USER_ID": "1784", "GITHUB_REPOSITORY": "o/r"}


class World:
    """Fake dependencies that record what happened."""
    def __init__(self, tmp_path):
        self.root, self.events, self.rendered_ids = tmp_path, [], []
        self.fail_wait = False
        self.li_calls, self.li_fail = [], 0
        self.th_calls, self.th_fail = [], 0
        self.deps = Deps(
            render_set=self.render_set, verify_set=lambda rs: [], git_publish=self.git_publish,
            wait_for_urls=self.wait_for_urls, prepare_set=self.prepare_set, publish_set=self.publish_set,
            sync_repo=lambda: None, head_sha=lambda: "deadbeef", post_linkedin=self.post_linkedin,
            post_threads=self.post_threads, prepare_video_set=self.prepare_video_set,
            post_linkedin_video=lambda *a: "urn:li:ugcPost:0", post_youtube=lambda *a: "VID0",
            send_whatsapp=lambda *a: "wamid.0")

    def render_set(self, sel, app_cfg, out_dir, fps=30):
        self.rendered_ids.append(sel.item["id"])
        out_dir.mkdir(parents=True, exist_ok=True)
        slides = []
        for i in range(3):
            p = out_dir / f"slide_{i + 1}.jpg"
            p.write_bytes(b"x" * 10)
            slides.append(p)
        reel = out_dir / "reel.mp4"
        reel.write_bytes(b"y" * 20)
        return RenderedSet(slides=slides, reel=reel, story=reel, seconds=18.0)

    def git_publish(self, paths, message):
        self.events.append(("git", message))

    def wait_for_urls(self, expected, **kw):
        if self.fail_wait:
            raise TimeoutError("urls not live")
        self.events.append(("wait", len(expected)))

    def prepare_video_set(self, ig_id, token, url, caption, **kw):
        self.prepared_video = url
        self.events.append(("prepare", url.split("/")[-2]))
        return Prepared(None, "b", "c")

    def prepare_set(self, ig_id, token, urls, captions, **kw):
        self.last_urls = urls
        self.events.append(("prepare", urls.reel.split("/")[-2]))
        return Prepared("a", "b", "c")

    def publish_set(self, ig_id, token, prepared):
        self.events.append(("publish",))
        return {"post": "1", "reel": "2", "story": "3"}

    def post_linkedin(self, token, urn, text, tags, slides, alts):
        self.li_calls.append({"token": token, "urn": urn, "text": text, "tags": tags, "slides": slides, "alts": alts})
        if self.li_fail:
            self.li_fail -= 1
            raise LinkedInError("token expired")
        return "urn:li:share:99"

    def post_threads(self, uid, token, urls, text):
        self.th_calls.append({"uid": uid, "token": token, "urls": urls, "text": text})
        if self.th_fail:
            self.th_fail -= 1
            raise ThreadsError("boom")
        return "th-1"

    def count(self, name):
        return sum(1 for e in self.events if e[0] == name)


def banks_with(first_bad=0):
    good = lambda i: {"id": f"w{i}", "template": "ink", "caption": "Plain words.", "hashtags": ["#A"],
                      "slides": [{"kind": "hook", "text": "Hello"}, {"kind": "quote", "text": "Bye"}, {"kind": "hook", "text": "Again"}]}
    bad = lambda i: dict(good(i), caption="Nobody can see you")
    wp = [bad(i) if i < first_bad else good(i) for i in range(6)]
    return {"waypoint": wp, "scoremybiz": [dict(good(0), id="s0")]}


def go(world, mode="post", banks=None, env=ENV, day=DAY):
    return run(mode, day, root=world.root, env=env, deps=world.deps, banks=banks or banks_with())


def test_second_run_on_the_same_date_publishes_nothing(tmp_path):
    w = World(tmp_path)
    assert go(w) == 0 and w.count("publish") == 1
    assert go(w) == 0 and w.count("publish") == 1
    assert already_posted(tmp_path / "logs" / "posts.jsonl", DAY)


def test_lint_failure_falls_back_to_the_next_item(tmp_path):
    w = World(tmp_path)
    assert go(w, banks=banks_with(first_bad=1)) == 0
    assert w.rendered_ids == ["w1"]


def test_five_failing_items_exit_nonzero_without_rendering_or_posting(tmp_path):
    w = World(tmp_path)
    assert go(w, banks=banks_with(first_bad=5)) == 1
    assert w.rendered_ids == [] and w.count("publish") == 0


def test_pause_switch_stops_everything(tmp_path):
    w = World(tmp_path)
    assert go(w, env=dict(ENV, PAUSE="1")) == 0
    assert w.rendered_ids == []
    (tmp_path / "PAUSE").write_text("")
    assert go(w) == 0 and w.rendered_ids == []


def test_urls_not_live_fails_before_any_instagram_call(tmp_path):
    w = World(tmp_path)
    w.fail_wait = True
    assert go(w) == 1
    assert w.count("prepare") == 0 and w.count("publish") == 0


def test_render_mode_neither_commits_nor_posts(tmp_path):
    w = World(tmp_path)
    assert go(w, mode="render", env={}) == 0
    assert w.count("git") == 0 and w.count("prepare") == 0 and w.count("publish") == 0 and w.rendered_ids


def test_prepare_mode_prepares_but_does_not_publish(tmp_path):
    w = World(tmp_path)
    assert go(w, mode="prepare") == 0
    assert w.count("prepare") == 1 and w.count("publish") == 0
    assert not already_posted(tmp_path / "logs" / "posts.jsonl", DAY)


def test_missing_secrets_fail_before_rendering(tmp_path):
    w = World(tmp_path)
    assert go(w, env={}) == 1
    assert w.rendered_ids == []


def test_intent_is_logged_before_publishing(tmp_path):
    w = World(tmp_path)
    order = []
    orig = w.deps.publish_set
    def spy(ig, tok, prep):
        order.append((tmp_path / "logs" / "posts.jsonl").read_text())
        return orig(ig, tok, prep)
    w.deps.publish_set = spy
    go(w)
    assert '"status": "publishing"' in order[0]
    last = json.loads((tmp_path / "logs" / "posts.jsonl").read_text().splitlines()[-1])
    assert last["status"] == "published" and last["ids"]["reel"] == "2"


def test_wait_for_urls_retries_until_sizes_match_then_times_out():
    sizes = iter([None, 5, 10])
    calls = []
    def fetch(url):
        calls.append(url)
        return next(sizes)
    wait_for_urls({"u": 10}, timeout_s=100, fetch=fetch, sleep=lambda s: None, clock=iter(range(0, 1000, 5)).__next__)
    assert len(calls) == 3
    with pytest.raises(TimeoutError):
        wait_for_urls({"u": 10}, timeout_s=10, fetch=lambda u: None, sleep=lambda s: None, clock=iter(range(0, 1000, 5)).__next__)


def test_prune_old_removes_only_old_day_folders(tmp_path):
    out = tmp_path / "out"
    for d in ("2026-09-01", "2026-10-05", "2026-10-11"):
        (out / d).mkdir(parents=True)
        (out / d / "f.txt").write_text("x")
    (out / "notes").mkdir()
    prune_old(out, DAY, keep_days=14)
    assert sorted(p.name for p in out.iterdir()) == ["2026-10-05", "2026-10-11", "notes"]


def log_path(tmp_path):
    return tmp_path / "logs" / "posts.jsonl"


def seed_log(tmp_path, status, ids=None):
    lp = log_path(tmp_path)
    lp.parent.mkdir(parents=True, exist_ok=True)
    entry = {"date": DAY.isoformat(), "status": status}
    if ids:
        entry["ids"] = ids
    lp.write_text(json.dumps(entry) + "\n")


def test_repo_is_synced_before_the_already_posted_check(tmp_path):
    w = World(tmp_path)
    w.deps.sync_repo = lambda: seed_log(tmp_path, "published")
    assert go(w) == 0
    assert w.rendered_ids == [] and w.count("publish") == 0


def test_a_day_stuck_at_publishing_fails_loudly_and_never_posts_again(tmp_path):
    w = World(tmp_path)
    seed_log(tmp_path, "publishing")
    assert go(w) == 1
    assert w.rendered_ids == [] and w.count("publish") == 0


def test_a_partial_publish_is_recorded_with_its_ids_and_fails(tmp_path):
    w = World(tmp_path)

    def half(ig, tok, prep):
        raise PartialPublish("reel failed", {"post": "1"})
    w.deps.publish_set = half
    assert go(w) == 1
    last = json.loads(log_path(tmp_path).read_text().splitlines()[-1])
    assert last["status"] == "partial" and last["ids"] == {"post": "1"}
    assert go(w) == 1 and w.count("prepare") == 1  # the rerun posts nothing new


def test_media_urls_pin_the_pushed_commit_not_a_branch(tmp_path):
    w = World(tmp_path)
    assert go(w) == 0
    for u in [*w.last_urls.slides, w.last_urls.reel, w.last_urls.story]:
        assert "/deadbeef/out/2026-10-11/" in u and "/main/" not in u


TUE = date(2026, 10, 13)  # LinkedIn day: Tuesday, and a Waypoint day


LI_ENV = dict(ENV, LINKEDIN_ACCESS_TOKEN="litok", LINKEDIN_PERSON_URN="urn:li:person:me")


def last_entry(tmp_path, channel):
    rows = [json.loads(x) for x in log_path(tmp_path).read_text().splitlines()]
    return [r for r in rows if r.get("channel", "instagram") == channel][-1]


def test_linkedin_posts_after_instagram_with_the_same_slides_and_a_clickable_link(tmp_path):
    w = World(tmp_path)
    assert go(w, env=LI_ENV, day=TUE) == 0
    assert w.count("publish") == 1 and len(w.li_calls) == 1
    call = w.li_calls[0]
    assert call["token"] == "litok" and call["urn"] == "urn:li:person:me" and len(call["slides"]) == 3
    assert "https://play.google.com/store/apps/details?id=com.arthvananalytics.waypoint" in call["text"]
    assert "Link in bio" not in call["text"] and len(call["alts"]) == 4
    assert last_entry(tmp_path, "linkedin")["status"] == "published"


def test_linkedin_is_skipped_quietly_without_credentials_and_in_prepare_mode(tmp_path):
    w = World(tmp_path)
    assert go(w, day=TUE) == 0 and w.li_calls == []
    w2 = World(tmp_path / "b")
    assert go(w2, mode="prepare", env=LI_ENV, day=TUE) == 0 and w2.li_calls == []


def test_linkedin_failure_exits_1_keeps_instagram_published_and_a_rerun_retries_only_linkedin(tmp_path):
    w = World(tmp_path)
    w.li_fail = 1
    assert go(w, env=LI_ENV, day=TUE) == 1
    assert w.count("publish") == 1 and last_entry(tmp_path, "linkedin")["status"] == "failed"
    assert last_entry(tmp_path, "instagram")["status"] == "published"
    assert go(w, env=LI_ENV, day=TUE) == 0
    assert w.count("publish") == 1 and w.rendered_ids == ["w1"] and len(w.li_calls) == 2
    assert go(w, env=LI_ENV, day=TUE) == 0 and len(w.li_calls) == 2  # already on LinkedIn: nothing more


def test_linkedin_posts_only_once_a_week_on_tuesday(tmp_path):
    w = World(tmp_path)
    for d in (date(2026, 10, 11), date(2026, 10, 12), date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 17)):
        assert go(w, env=LI_ENV, day=d) == 0
    assert w.li_calls == [] and w.count("publish") == 6
    assert go(w, env=LI_ENV, day=TUE) == 0 and len(w.li_calls) == 1
    assert go(w, env=LI_ENV, day=date(2026, 10, 20)) == 0 and len(w.li_calls) == 2  # next Tuesday


def test_a_rerun_on_a_non_linkedin_day_never_posts_to_linkedin(tmp_path):
    w = World(tmp_path)
    assert go(w, env=LI_ENV, day=date(2026, 10, 12)) == 0
    assert go(w, env=LI_ENV, day=date(2026, 10, 12)) == 0 and w.li_calls == []


TH_ENV = dict(ENV, THREADS_ACCESS_TOKEN="thtok", THREADS_USER_ID="9001")


def test_threads_posts_daily_after_instagram_with_the_pinned_slide_urls(tmp_path):
    w = World(tmp_path)
    assert go(w, env=TH_ENV) == 0 and go(w, env=TH_ENV, day=date(2026, 10, 12)) == 0
    assert len(w.th_calls) == 2
    c = w.th_calls[0]
    assert c["uid"] == "9001" and c["token"] == "thtok" and len(c["urls"]) == 3
    assert all("/deadbeef/out/2026-10-11/" in u for u in c["urls"])
    assert "play.google.com" in c["text"] and last_entry(tmp_path, "threads")["status"] == "published"


def test_threads_failure_is_isolated_and_retried_on_rerun(tmp_path):
    w = World(tmp_path)
    w.th_fail = 1
    assert go(w, env=TH_ENV) == 1
    assert last_entry(tmp_path, "instagram")["status"] == "published"
    assert last_entry(tmp_path, "threads")["status"] == "failed"
    assert go(w, env=TH_ENV) == 0 and len(w.th_calls) == 2 and w.count("publish") == 1
    assert go(w, env=TH_ENV) == 0 and len(w.th_calls) == 2


def test_threads_and_linkedin_both_retry_when_both_failed_on_a_tuesday(tmp_path):
    w = World(tmp_path)
    w.th_fail, w.li_fail = 1, 1
    env = dict(TH_ENV, **{k: v for k, v in LI_ENV.items() if k.startswith("LINKEDIN")})
    assert go(w, env=env, day=TUE) == 1
    assert go(w, env=env, day=TUE) == 0
    assert len(w.th_calls) == 2 and len(w.li_calls) == 2 and w.count("publish") == 1


def test_a_scheduled_story_replaces_the_bank_item_and_posts_reel_story_and_linkedin_video(tmp_path):
    w = World(tmp_path)
    (tmp_path / "stories" / "out").mkdir(parents=True)
    (tmp_path / "stories" / "out" / "lumi-friday-hi.mp4").write_bytes(b"v" * 30)
    (tmp_path / "stories" / "lumi_friday_hi.json").write_text(json.dumps({
        "id": "lumi-friday-hi", "app": "scoremybiz", "lang": "hi-IN", "post_on": "2026-10-12", "character": "lumi",
        "caption": "Meena's Friday, told by Lumi.", "hashtags": ["#Lumi"], "linkedin_text": "Meena's Friday.", "title": "शुक्रवार"}))
    w.li_videos = []
    w.deps.post_linkedin_video = lambda token, urn, text, tags, path, title: w.li_videos.append((text, str(path), title)) or "urn:li:ugcPost:5"
    env = dict(ENV, LINKEDIN_ACCESS_TOKEN="litok", LINKEDIN_PERSON_URN="urn:li:person:me")
    assert go(w, env=env, day=date(2026, 10, 12)) == 0
    assert w.rendered_ids == []                                 # no bank item rendered
    assert w.count("publish") == 1 and w.prepared_video == "https://raw.githubusercontent.com/o/r/deadbeef/out/2026-10-12/story.mp4"
    assert len(w.li_videos) == 1 and "play.google.com" in w.li_videos[0][0] and w.li_videos[0][2] == "शुक्रवार"
    assert last_entry(tmp_path, "instagram")["item"] == "lumi-friday-hi" and last_entry(tmp_path, "linkedin")["status"] == "published"
    assert w.th_calls == []                                     # Threads needs images; skipped on story days
    assert go(w, env=env, day=date(2026, 10, 12)) == 0 and w.count("publish") == 1


def test_a_missed_story_is_posted_on_the_next_run_and_never_twice(tmp_path):
    w = World(tmp_path)
    (tmp_path / "stories" / "out").mkdir(parents=True)
    for sid, day in (("s-tue", "2026-10-13"), ("s-wed", "2026-10-14")):
        (tmp_path / "stories" / "out" / f"{sid}.mp4").write_bytes(b"v")
        (tmp_path / "stories" / f"{sid}.json").write_text(json.dumps({"id": sid, "app": "waypoint", "post_on": day, "character": "mira", "caption": "c", "hashtags": [], "title": "t"}))
    # access returns on Friday: Tuesday's story goes first, Saturday gets Wednesday's, Sunday is a normal day
    assert go(w, day=date(2026, 10, 16)) == 0 and last_entry(tmp_path, "instagram")["item"] == "s-tue"
    assert go(w, day=date(2026, 10, 17)) == 0 and last_entry(tmp_path, "instagram")["item"] == "s-wed"
    assert go(w, day=date(2026, 10, 18)) == 0 and last_entry(tmp_path, "instagram")["item"] == "s0"
    assert w.count("publish") == 3


def test_youtube_short_is_uploaded_after_instagram_when_the_channel_is_configured(tmp_path):
    w = World(tmp_path)
    ups = []
    w.deps.post_youtube = lambda channel, path, title, desc, play, tags: ups.append((channel["refresh_token"], str(path), title, play)) or "VID1"
    env = dict(ENV, YT_CLIENT_ID="cid", YT_CLIENT_SECRET="sec", YT_SGLEARNING_REFRESH_TOKEN="rt-sg", YT_ARTHVAN_REFRESH_TOKEN="rt-ar")
    assert go(w, env=env) == 0                                    # waypoint day: both channels
    assert sorted(u[0] for u in ups) == ["rt-ar", "rt-sg"] and all(u[1].endswith("reel.mp4") and "arthvananalytics.waypoint" in u[3] for u in ups)
    assert last_entry(tmp_path, "youtube:sglearning")["status"] == "published" and last_entry(tmp_path, "youtube:arthvan")["id"] == "VID1"
    assert go(w, env=env, day=date(2026, 10, 12)) == 0 and len(ups) == 4   # scoremybiz day: both channels again
    assert go(w, env=dict(ENV), day=date(2026, 10, 13)) == 0 and len(ups) == 4  # no YouTube config: skipped quietly


def test_youtube_failure_is_isolated_and_retried(tmp_path):
    w = World(tmp_path)
    calls = []
    def flaky(channel, path, title, desc, play, tags):
        calls.append(1)
        if len(calls) == 1: raise YouTubeError("quota")
        return "VID2"
    w.deps.post_youtube = flaky
    env = dict(ENV, YT_CLIENT_ID="cid", YT_CLIENT_SECRET="sec", YT_SGLEARNING_REFRESH_TOKEN="rt")
    assert go(w, env=env) == 1 and last_entry(tmp_path, "instagram")["status"] == "published"
    assert go(w, env=env) == 0 and len(calls) == 2 and w.count("publish") == 1


def test_whatsapp_status_video_goes_to_the_founder_after_instagram_and_retries_alone(tmp_path):
    w = World(tmp_path)
    sent = []
    w.deps.send_whatsapp = lambda cfg, url, app, caption: sent.append((cfg["to"], url, app)) or "wamid.9"
    env = dict(ENV, GUPSHUP_APP_ID="a", GUPSHUP_API_KEY="k", WA_STATUS_TO="+2348120000000", WA_STATUS_TEMPLATE="daily_status_video")
    assert go(w, env=env) == 0
    assert len(sent) == 1 and sent[0][0] == "+2348120000000" and sent[0][1].endswith("/reel.mp4") and sent[0][2] == "Waypoint"
    assert last_entry(tmp_path, "whatsapp")["status"] == "published"
    assert go(w, env=env) == 0 and len(sent) == 1
    assert go(w, env=dict(ENV), day=date(2026, 10, 12)) == 0 and len(sent) == 1   # not configured: skipped
