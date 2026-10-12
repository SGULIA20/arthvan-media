import json
from datetime import date

from engine import broll
from engine.broll_library import plan, unmade

SHOTS = [{"prompt": f"shot {i}"} for i in range(40)]


def test_plan_takes_unmade_prompts_in_order_up_to_todays_gap(tmp_path):
    (tmp_path / "l.json").write_text(json.dumps({"spent_inr": 0.0}))
    (tmp_path / "c").mkdir(); (tmp_path / "c" / (broll.key_for("shot 0", 8) + ".mp4")).write_bytes(b"x")   # already made
    todo = plan(SHOTS, today=date(2026, 10, 14), ledger_path=tmp_path / "l.json", cache=tmp_path / "c")
    target = broll.pace(tmp_path / "l.json", date(2026, 10, 14))["target_inr"]        # two days in: about ₹950
    assert todo and todo[0]["prompt"] == "shot 1" and len(todo) == int(target // (8 * broll.INR_PER_SECOND))


def test_plan_is_empty_when_ahead_of_plan_finished_or_past_deadline(tmp_path):
    (tmp_path / "l.json").write_text(json.dumps({"spent_inr": 5000.0}))
    assert plan(SHOTS, today=date(2026, 10, 14), ledger_path=tmp_path / "l.json", cache=tmp_path / "c") == []   # ahead of plan
    (tmp_path / "l.json").write_text(json.dumps({"spent_inr": 28000.0}))
    assert plan(SHOTS, today=date(2026, 11, 20), ledger_path=tmp_path / "l.json", cache=tmp_path / "c", inr=500) == []
    (tmp_path / "l.json").write_text(json.dumps({"spent_inr": 100.0}))
    assert plan(SHOTS, today=date(2026, 12, 11), ledger_path=tmp_path / "l.json", cache=tmp_path / "c", inr=500) == []


def test_explicit_amount_never_exceeds_what_is_left_of_the_credit(tmp_path):
    (tmp_path / "l.json").write_text(json.dumps({"spent_inr": 27900.0}))
    todo = plan(SHOTS, today=date(2026, 11, 1), ledger_path=tmp_path / "l.json", cache=tmp_path / "c", inr=5000)
    assert len(todo) == 1                                                            # ₹100 left buys one ₹56 shot


def test_library_prompts_are_valid():
    from engine.config import ROOT
    shots = json.loads((ROOT / "content" / "shots.json").read_text())["shots"]
    assert len(shots) >= 100 and all(s["prompt"].endswith(".") and s["app"] in ("scoremybiz", "waypoint", "both") for s in shots)
    assert len({s["prompt"] for s in shots}) == len(shots)                           # no duplicates, no double spend
