import subprocess

import numpy as np

from engine.music import synth, track_info, write_m4a

SR = 22050  # small rate keeps tests fast; the function must honour it


def test_same_seed_is_deterministic_and_different_seeds_differ():
    a = synth("scoremybiz", 1, 3.0, sr=SR)
    b = synth("scoremybiz", 1, 3.0, sr=SR)
    c = synth("scoremybiz", 2, 3.0, sr=SR)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_shape_dtype_level_and_length():
    x = synth("waypoint", 5, 4.0, sr=SR)
    assert x.dtype == np.float32 and x.shape == (4 * SR, 2)
    assert np.max(np.abs(x)) <= 0.9
    assert np.sqrt(np.mean(x ** 2)) > 0.01


def test_apps_have_different_moods():
    a, b = track_info("scoremybiz", 1), track_info("waypoint", 1)
    assert a["bpm"] != b["bpm"] and a["mode"] != b["mode"]


def test_starts_and_ends_softly():
    x = synth("scoremybiz", 3, 5.0, sr=SR)
    assert np.max(np.abs(x[:200])) < 0.2
    assert np.max(np.abs(x[-200:])) < 0.05


def test_write_m4a_makes_an_aac_file_of_the_right_length(tmp_path):
    x = synth("waypoint", 7, 3.0, sr=SR)
    out = tmp_path / "t.m4a"
    write_m4a(x, out, sr=SR)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name:format=duration", "-of", "default=nw=1", str(out)],
        capture_output=True, text=True, check=True).stdout
    assert "codec_name=aac" in probe
    dur = float(probe.split("duration=")[1].split()[0])
    assert abs(dur - 3.0) < 0.2


def _band_share(x, sr, lo, hi):
    spec = np.abs(np.fft.rfft(x.mean(axis=1))) ** 2
    freqs = np.fft.rfftfreq(x.shape[0], 1 / sr)
    return float(spec[(freqs >= lo) & (freqs < hi)].sum() / spec.sum())


def test_tracks_are_audible_on_phone_speakers_and_not_hissy():
    for app in ("scoremybiz", "waypoint"):
        for seed in (1, 2, 3):
            x = synth(app, seed, 8.0, sr=44100)
            assert _band_share(x, 44100, 0, 200) < 0.35, (app, seed, "too much deep bass for phones")
            assert _band_share(x, 44100, 250, 4000) > 0.5, (app, seed, "too little mid range")
            assert _band_share(x, 44100, 4000, 22050) < 0.05, (app, seed, "hissy")
