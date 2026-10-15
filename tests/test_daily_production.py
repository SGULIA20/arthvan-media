import json
from datetime import date

from engine import daily_production as dp

NOW = date(2026, 10, 15)


def story(sid, app="scoremybiz", lines=7, post_on="2026-10-20"):
    return {"id": sid, "app": app, "lang": "en", "post_on": post_on, "scenes": [{"layout": "clip", "vo": "x"}] * lines}


def setup(monkeypatch, tmp_path, english, convert):
    monkeypatch.setattr(dp, "pending_english", lambda root: english)
    monkeypatch.setattr(dp, "backlog", lambda root, failures=None: convert)
    monkeypatch.setattr(dp, "library", type("L", (), {"LANGUAGES": {"hi": "Hindi", "ta": "Tamil"}, "sync": staticmethod(lambda *a: None), "LIBRARY": tmp_path})())
    monkeypatch.setattr(dp.broll, "spent_inr", lambda *a, **k: 1000.0)
    monkeypatch.setattr(dp, "load_apps", lambda: {"scoremybiz": {}, "waypoint": {}})
    import engine.story as st
    monkeypatch.setattr(st, "shot_plan", lambda s: [(0, "p", [], True)])                # every shot already cached


def test_english_originals_come_first_then_conversions_until_the_voice_budget_is_used(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, [story("a-en")], [("hi", story("b-en")), ("hi", story("c-en")), ("ta", story("d-en"))])
    r = dp.run(tmp_path, dry=True, budget=21, now=NOW, log=tmp_path / "log")
    assert [m[0] for m in r["made"]] == ["a-en", "b-hi", "c-hi"] and r["stopped"] == "voice budget"        # 3 x 7 = 21 lines, the fourth does not fit


def test_the_run_stops_for_the_day_when_google_says_the_voice_allowance_is_gone(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, [], [("hi", story("b-en")), ("hi", story("c-en"))])
    built = []
    def build(path, root, env=None):
        built.append(path.name); return ("quota", "voice allowance used up")
    class T:                                                                              # the translator is not needed for this check
        ensure_files = staticmethod(lambda base, app, cfg, lang, root, ask, strict=False: (tmp_path / "tr.json"))
        TranslationRejected = Exception
    (tmp_path / "tr.json").write_text(json.dumps({"title": "t", "caption": "c", "scenes": [{"vo": "v"}] * 7}))
    (tmp_path / "stories").mkdir(); (tmp_path / "stories" / "out").mkdir()
    monkeypatch.setattr(dp, "translator", T)
    monkeypatch.setattr(dp.localize, "localize", lambda base, tr, lang: {"id": "b-hi"})
    r = dp.run(tmp_path, build=build, ask=lambda *a, **k: "", now=NOW, log=tmp_path / "log")
    assert built == ["b_hi.json"] and r["stopped"] == "voice allowance" and r["made"] == []          # only the first was tried


def test_failures_are_counted_and_forgotten_after_a_success(tmp_path):
    log = tmp_path / "log"
    for st in ("failed", "failed", "made", "failed"):
        dp._log({"id": "x-hi", "status": st}, log)
    assert dp._failures(log) == {"x-hi": 1}


def test_the_summary_says_what_was_made_what_is_left_and_why_it_stopped():
    r = {"made": [("a-hi", ""), ("b-hi", ""), ("c-ta", "")], "failed": [("d-ta", "render ran over 25 minutes")], "stopped": "voice budget", "pending_english": 0, "left": 120, "english": 0}
    t = dp.summary(r, "Veo credit: x")
    assert "3 Reels made (Hindi 2, Tamil 1)" in t and "Conversions still to do: 120 (about 10 days)" in t and "d-ta: render ran over 25 minutes" in t and "carries on tomorrow" in t and t.endswith("Veo credit: x")


def test_a_network_outage_stops_the_run_and_is_not_counted_as_a_failed_try(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, [story("a-en"), story("b-en")], [])
    built = []
    def build(path, root, env=None):
        built.append(path.name); return ("network", "URLError: nodename nor servname provided")
    r = dp.run(tmp_path, build=build, wait_net=lambda: False, now=NOW, log=tmp_path / "log")
    assert built == ["a_en.json"] and r["stopped"] == "network" and r["failed"] == []                # stops at the first, does not burn the others
    assert dp._failures(tmp_path / "log") == {}                                                      # and no try is spent


def test_the_build_is_tried_again_once_the_network_is_back(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, [story("a-en")], [])
    answers = iter([("network", "URLError"), ("made", "")])
    r = dp.run(tmp_path, build=lambda *a, **k: next(answers), wait_net=lambda: True, now=NOW, log=tmp_path / "log")
    assert [m[0] for m in r["made"]] == ["a-en"] and r["stopped"] == ""


def test_network_errors_are_recognised_and_the_wait_gives_up_after_its_limit():
    assert dp.is_network_problem("urllib.error.URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>")
    assert not dp.is_network_problem("ValueError: scene 3 has no picture")
    slept = []
    assert dp.wait_for_network(max_seconds=120, step=60, up=lambda: False, sleep=slept.append) is False and slept == [60, 60]
    assert dp.wait_for_network(max_seconds=120, step=60, up=lambda: True, sleep=slept.append) is True


def test_a_render_interrupted_by_a_sleeping_mac_is_retried_and_not_counted_as_a_failed_try(monkeypatch, tmp_path):
    assert dp.is_interrupted("playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded.\nCall log:\n  - fonts loaded")
    assert not dp.is_interrupted("ValueError: scene 3 has no picture")
    assert not dp.is_interrupted("urllib.error.URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>")
    setup(monkeypatch, tmp_path, [story("a-en"), story("b-en")], [])
    answers = iter([("interrupted", "x"), ("interrupted", "x"), ("made", ""), ("interrupted", "x"), ("interrupted", "x"), ("interrupted", "x")])
    r = dp.run(tmp_path, build=lambda *a, **k: next(answers), wait_net=lambda: True, now=NOW, log=tmp_path / "log")
    assert [m[0] for m in r["made"]] == ["a-en"]                                   # the first came right on the third try
    assert [f[0] for f in r["failed"]] == ["b-en"] and dp._failures(tmp_path / "log") == {}      # the second gave up for today without spending a try


def test_the_day_is_marked_done_on_googles_pacific_calendar(tmp_path):
    from datetime import datetime, timezone
    m = tmp_path / "done.json"
    t = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)                 # 01:00 Pacific on the 15th
    assert not dp.day_is_done(m, t)
    dp.mark_day_done("voice allowance", m, t)
    assert dp.day_is_done(m, datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc))        # same Pacific day, later
    assert not dp.day_is_done(m, datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc))      # next Pacific day: work again
    assert dp.quota_day(datetime(2026, 10, 15, 6, 59, tzinfo=timezone.utc)) == "2026-10-14"    # before 07:00 UTC it is still the 14th there


def test_once_the_credit_is_gone_conversions_come_first_then_filmed_english_then_cutout_english(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, [story("a-en"), story("b-en")], [("hi", story("c-en")), ("hi", story("d-en"))])
    import engine.story as st
    monkeypatch.setattr(st, "shot_plan", lambda s: [(0, "p", [], s["id"] == "a-en")])          # a-en is fully filmed, b-en still needs a paid shot
    monkeypatch.setattr(dp.broll, "spent_inr", lambda *a, **k: 27900.0)                        # the credit is used up
    r = dp.run(tmp_path, dry=True, budget=100, now=NOW, log=tmp_path / "log")
    assert [m[0] for m in r["made"]] == ["c-hi", "d-hi", "a-en", "b-en"]                       # conversions, then the already filmed original, then the cut-out one
    assert dict(r["made"])["b-en"] == "English, free cut-out style"


def test_an_approved_backup_voice_model_takes_over_a_whole_reel_when_the_first_is_used_up(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, [story("a-en"), story("b-en")], [])
    monkeypatch.setattr(dp, "voice_models", lambda path=None: [None, "backup-tts"])
    seen = []
    def build(path, root, env=None):
        m = (env or {}).get("TTS_MODEL"); seen.append((path.name, m))
        return ("quota", "used up") if m is None else ("made", "")
    r = dp.run(tmp_path, build=build, wait_net=lambda: True, now=NOW, log=tmp_path / "log")
    assert seen == [("a_en.json", None), ("a_en.json", "backup-tts"), ("b_en.json", "backup-tts")]      # the first Reel is made again on the backup, later Reels go straight to it
    assert [m[0] for m in r["made"]] == ["a-en", "b-en"] and r["stopped"] == ""


def test_voice_models_is_just_the_normal_model_until_a_file_approves_backups(tmp_path):
    assert dp.voice_models(tmp_path / "none.json") == [None]
    f = tmp_path / "v.json"; f.write_text('{"backups": ["m1", "m2"]}')
    assert dp.voice_models(f) == [None, "m1", "m2"]
