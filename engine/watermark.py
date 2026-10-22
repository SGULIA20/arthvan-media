"""A faint, centred app icon on every Reel frame (founder, 22 Oct 2026): a crop or a re-upload cannot remove it, and at 10 % opacity it
does not get in the way of watching. Used by both renderers through extra ffmpeg inputs and a filter."""
from pathlib import Path

from .config import ROOT

ALPHA = 0.10
SHARE = 0.34          # a third of the shorter side


def icon_for(app: str) -> Path | None:
    import json
    apps = json.loads((ROOT / "content" / "apps.json").read_text())
    rel = (apps.get(app) or {}).get("icon")
    p = ROOT / rel if rel else None
    return p if p and p.exists() else None


def ffmpeg_parts(icon: Path | None, width: int, height: int, video_in: str = "[0:v]", icon_index: int = 2) -> tuple:
    """(extra_inputs, filter_complex, mapped_video_label). With no icon: ([], None, video_in)."""
    if icon is None:
        return [], None, video_in
    size = int(min(width, height) * SHARE)
    x, y = (width - size) // 2, (height - size) // 2
    fc = (f"[{icon_index}:v]scale={size}:{size},format=rgba,colorchannelmixer=aa={ALPHA}[wm];"
          f"{video_in}[wm]overlay={x}:{y}:shortest=1[vout]")
    return ["-loop", "1", "-i", str(icon)], fc, "[vout]"
