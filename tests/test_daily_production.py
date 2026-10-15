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
