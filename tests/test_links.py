import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from engine import links
from engine.lint import build_captions, build_threads_text, story_captions

ROOT = Path(__file__).resolve().parent.parent
APPS = json.loads((ROOT / "content" / "apps.json").read_text())


def test_play_link_carries_an_encoded_referrer_that_decodes_to_the_utm_tags():
    url = links.tracked_play_url(APPS["waypoint"]["play_url"], "instagram", "reel", "mira-ekbaat-hi")
    q = parse_qs(urlparse(url).query)
    assert q["id"] == ["com.arthvananalytics.waypoint"]
    assert parse_qs(unquote(q["referrer"][0])) == {"utm_source": ["instagram"], "utm_medium": ["reel"], "utm_campaign": ["mira-ekbaat-hi"]}
    assert len(q["referrer"][0]) < 256                                                      # Google Play's limit for the referrer value


def test_both_apps_get_their_own_tagged_link_and_youtube_channel_in_every_caption():
    item = {"id": "demo-1", "caption": "Ek baat.", "reel_caption": "Ek baat reel.", "hashtags": ["#A"], "slides": [{"kind": "stat", "text": "x", "value": "1"}]}
    expected_channel = {"scoremybiz": "@sanjeev_gulia", "waypoint": "@sgmythworld"}
    for app, handle in expected_channel.items():
        cfg = links.for_post(APPS[app], "instagram", "slides", "demo-1")
        for cap in build_captions(cfg, item):
            assert "referrer=utm_source%3Dinstagram%26utm_medium%3Dslides%26utm_campaign%3Ddemo-1" in cap and handle in cap
        th = build_threads_text(links.for_post(APPS[app], "threads", "post", "demo-1"), item)
        assert "utm_source%3Dthreads" in th and handle in th and len(th) <= 500
        ig, _li, _tags = story_captions(links.for_post(APPS[app], "instagram", "reel", "demo-1"), {"id": "demo-1", "caption": "Kahani.", "hashtags": []})
        assert "utm_medium%3Dreel" in ig and handle in ig


def test_for_post_does_not_change_the_shared_config():
    before = APPS["scoremybiz"]["play_url"]
    links.for_post(APPS["scoremybiz"], "threads", "post", "x")
    assert APPS["scoremybiz"]["play_url"] == before and "referrer" not in before
