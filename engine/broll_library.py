"""Build the shot library a little every day: generate unmade prompts from content/shots.json until today's rupee
target on the plan to finish the credit by 10 Dec 2026 is met. Runs on the founder's Mac (gcloud sign-in), never in CI.
python -m engine.broll_library            generate up to today's target
python -m engine.broll_library --inr 700  generate about this much, whatever the plan says
"""
import json
import sys
from datetime import date
from pathlib import Path

from . import broll
from .config import ROOT

SHOTS = ROOT / "content" / "shots.json"


def unmade(shots: list, cache: Path = broll.BROLL_DIR) -> list:
    return [s for s in shots if not (Path(cache) / (broll.key_for(s["prompt"], s.get("seconds", 8)) + ".mp4")).exists()]


def plan(shots: list, *, today: date = None, ledger_path: Path = broll.LEDGER, cache: Path = broll.BROLL_DIR, inr: float = None) -> list:
    """The prompts to generate now: unmade ones, in order, until `inr` (default: the gap between the plan's figure for
    today and what has been spent) is covered. Nothing once the credit is finished or the deadline has passed."""
    p = broll.pace(ledger_path, today)
    if p["finished"]:
        return []
    budget = (p["target_inr"] - p["spent_inr"]) if inr is None else inr
    budget = min(budget, p["credit_inr"] - p["spent_inr"])
    chosen, cost = [], 0.0
    for s in unmade(shots, cache):
        c = s.get("seconds", 8) * broll.INR_PER_SECOND
        if cost + c > budget:
            break
        chosen.append(s); cost += c
    return chosen


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    inr = float(argv[argv.index("--inr") + 1]) if "--inr" in argv else None
    shots = json.loads(SHOTS.read_text())["shots"]
    todo = plan(shots, inr=inr)
    print(broll.status_line())
    if not todo:
        print("nothing to generate today"); return 0
    made = 0
    for s in todo:
        try:
            broll.clip(s["prompt"], seconds=s.get("seconds", 8)); made += 1
            print(f"made: {s['prompt'][:80]}")
        except broll.BRollError as e:
            print(f"stopped: {e}"); break
    print(f"{made} shot(s) made. {broll.status_line()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
