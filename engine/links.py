"""Tagged Play links and the YouTube channel line for every app post (founder, 22 Oct 2026).

Every Play link carries a referrer tag (source, medium, campaign), so Play Console's acquisition report shows which platform and which post
produced each install. The tag is read by Google Play itself; the apps need no code for it."""
from urllib.parse import quote


def tracked_play_url(base: str, source: str, medium: str, campaign: str) -> str:
    ref = f"utm_source={source}&utm_medium={medium}&utm_campaign={campaign}"
    return f"{base}{'&' if '?' in base else '?'}referrer={quote(ref, safe='')}"


def for_post(app_cfg: dict, source: str, medium: str, campaign: str) -> dict:
    """A copy of the app's config whose play_url is tagged for this platform and post; the caption builders then need no change."""
    cfg = dict(app_cfg)
    cfg["play_url"] = tracked_play_url(app_cfg["play_url"], source, medium, str(campaign))
    return cfg


def youtube_line(app_cfg: dict) -> str:
    url = app_cfg.get("youtube_url")
    return f"More videos on YouTube: {url}" if url else ""
