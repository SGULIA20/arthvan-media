import subprocess

from engine.qa import blink_count


def _video(path, filtergraph):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=144x256:r=30:d=2", "-vf", filtergraph, "-pix_fmt", "yuv420p", str(path)], check=True)


def test_a_steady_video_and_a_fade_have_no_blinks_but_a_dark_frame_does(tmp_path):
    _video(tmp_path / "steady.mp4", "null")
    _video(tmp_path / "fade.mp4", "fade=t=out:st=0.5:d=1")
    _video(tmp_path / "blink.mp4", "drawbox=x=0:y=0:w=144:h=256:color=black:t=fill:enable='between(n,30,30)'")
    assert blink_count(tmp_path / "steady.mp4") == 0
    assert blink_count(tmp_path / "fade.mp4") == 0
    assert blink_count(tmp_path / "blink.mp4") == 1
