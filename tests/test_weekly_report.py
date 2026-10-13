import json
from datetime import date
from types import SimpleNamespace as R

from engine import weekly_report as wr

DAY = date(2026, 10, 17)


def runner(answers):
    def run(cmd, **kw):
        ref = cmd[cmd.index("--project-ref") + 1]
        out = answers[ref]
        return R(returncode=0, stdout=out, stderr="") if not out.startswith("ERR") else R(returncode=1, stdout="", stderr=out[4:])
    return run


SMB = json.dumps({"rows": [{"total": "6", "new_7d": "3", "paid": "1"}]})
WP = json.dumps([{"total": 40, "new_7d": 9}])


def led(tmp_path, spent=12436.0):
    p = tmp_path / "l.json"; p.write_text(json.dumps({"spent_inr": spent})); return p


def test_report_names_users_in_both_apps_and_the_credit(tmp_path):
    text, state = wr.build(DAY, run=runner({"xiidltxcsetevaverqkx": SMB, "zoyopcfnglpcnlraokob": WP}), wallet=lambda: 9.93, state_path=tmp_path / "s.json", ledger=led(tmp_path))
    assert "ScoreMyBiz: 6 in total, 3 new in the last 7 days, 1 paid" in text and "Waypoint: 40 in total, 9 new in the last 7 days" in text
    assert "₹12,436 of ₹28,000 used" in text and "$9.93 left" in text and "console.anthropic.com" in text and "aistudio.google.com" in text
    assert state["users"] == {"ScoreMyBiz": 6, "Waypoint": 40} and state["veo_inr"] == 12436 and state["wallet_usd"] == 9.93


def test_second_week_shows_what_changed(tmp_path):
    s = tmp_path / "s.json"; s.write_text(json.dumps({"users": {"ScoreMyBiz": 4, "Waypoint": 40}, "veo_inr": 12000, "wallet_usd": 9.95}))
    text, _ = wr.build(DAY, run=runner({"xiidltxcsetevaverqkx": SMB, "zoyopcfnglpcnlraokob": WP}), wallet=lambda: 9.93, state_path=s, ledger=led(tmp_path))
    assert "(+2 since last report)" in text and "(+0 since last report)" in text and "This week: +₹436." in text and "used $0.02 this week" in text


def test_an_unreadable_source_is_said_plainly_and_the_rest_still_goes(tmp_path):
    def broken(): raise OSError("offline")
    text, state = wr.build(DAY, run=runner({"xiidltxcsetevaverqkx": "ERR permission denied", "zoyopcfnglpcnlraokob": WP}), wallet=broken, state_path=tmp_path / "s.json", ledger=led(tmp_path))
    assert "ScoreMyBiz: could not read (permission denied)" in text and "Waypoint: 40 in total" in text and "wallet (Gupshup): could not read" in text
    assert state["users"] == {"Waypoint": 40}


def test_wallet_not_set_up_is_said_not_hidden(tmp_path):
    text, _ = wr.build(DAY, run=runner({"xiidltxcsetevaverqkx": SMB, "zoyopcfnglpcnlraokob": WP}), wallet=None, state_path=tmp_path / "s.json", ledger=led(tmp_path))
    assert "not connected to this report yet" in text


def test_the_cli_json_is_read_whatever_its_wrapper_and_noise_before_it(tmp_path):
    noisy = "A new version is available\n" + json.dumps({"result": {"data": [{"total": 2}]}})
    assert wr.user_counts("x", "select 1", runner({"x": noisy})) == {"total": 2}


def test_wallet_call_reads_the_balance(tmp_path):
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, *a): return b'{"status":"success","wallet":{"balance":9.932}}'
    seen = {}
    def opener(req, timeout=None): seen["url"] = req.full_url; seen["key"] = req.get_header("Apikey"); return Resp()
    assert wr.wallet_usd("APP", "K", opener) == 9.932 and seen["url"].endswith("/wa/app/APP/wallet/balance") and seen["key"] == "K"
