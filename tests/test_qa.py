import subprocess

from engine.qa import blink_count, decode_errors


def _video(path, filtergraph):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=144x256:r=30:d=2", "-vf", filtergraph, "-pix_fmt", "yuv420p", str(path)], check=True)


def test_a_steady_video_and_a_fade_have_no_blinks_but_a_dark_frame_does(tmp_path):
    _video(tmp_path / "steady.mp4", "null")
    _video(tmp_path / "fade.mp4", "fade=t=out:st=0.5:d=1")
    _video(tmp_path / "blink.mp4", "drawbox=x=0:y=0:w=144:h=256:color=black:t=fill:enable='between(n,30,30)'")
    assert blink_count(tmp_path / "steady.mp4") == 0
    assert blink_count(tmp_path / "fade.mp4") == 0
    assert blink_count(tmp_path / "blink.mp4") == 1


def test_decode_errors_are_zero_for_a_good_file_and_positive_for_a_truncated_one(tmp_path):
    _video(tmp_path / "good.mp4", "null")
    data = (tmp_path / "good.mp4").read_bytes()
    (tmp_path / "bad.mp4").write_bytes(data[: len(data) // 2] + b"\x00\xff" * 5000 + data[len(data) // 2 + 400:])
    assert decode_errors(tmp_path / "good.mp4") == 0
    assert decode_errors(tmp_path / "bad.mp4") > 0
