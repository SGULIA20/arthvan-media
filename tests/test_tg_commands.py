import json
import time
from datetime import date

from engine import tg_commands as tc

CFG = {"token": "TOK", "chat_id": "42"}
DAY = date(2026, 10, 13)


def upd(uid, text, chat=42, age=0):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text, "date": int(time.time()) - age}}


def run(tmp_path, updates, change=None, flag=False):
    (tmp_path / "logs").mkdir(exist_ok=True); (tmp_path / "logs" / "posts.jsonl").write_text("")
    if flag: (tmp_path / "PAUSE").write_text("x")
    sent, confirmed, changes = [], [], []
    def call(token, method, body):
        if "offset" in body: confirmed.append(body["offset"]); return {"result": []}
        return {"result": updates}
    n = tc.poll(CFG, tmp_path, call=call, send=lambda cfg, text: sent.append(text), change=change or (lambda *a: changes.append(a)), day=DAY)
    return n, sent, confirmed, changes


def test_pause_writes_the_flag_commits_it_and_confirms_the_command(tmp_path):
    n, sent, confirmed, changes = run(tmp_path, [upd(7, "/pause")])
    assert n == 1 and (tmp_path / "PAUSE").exists() and confirmed == [8] and sent[0].startswith("⏸ Paused")
    assert changes[0][1] == ["PAUSE"] and changes[0][3].startswith("pause posting")


def test_resume_removes_the_flag(tmp_path):
    n, sent, confirmed, changes = run(tmp_path, [upd(1, "/resume")], flag=True)
    assert not (tmp_path / "PAUSE").exists() and changes[0][2] == ["PAUSE"] and sent[0].startswith("▶️")


def test_pausing_twice_and_resuming_when_on_change_nothing(tmp_path):
    _, sent, _, changes = run(tmp_path, [upd(1, "/pause")], flag=True)
    assert sent[0].startswith("Already paused") and changes == []
    _, sent, _, changes = run(tmp_path / "b", [upd(1, "/resume")]) if (tmp_path / "b").mkdir() is None else None
    assert sent[0] == "Posting is already on." and changes == []


def test_strangers_are_ignored_but_their_updates_are_still_cleared(tmp_path):
    n, sent, confirmed, changes = run(tmp_path, [upd(5, "/pause", chat=999)])
    assert n == 0 and sent == [] and confirmed == [6] and not (tmp_path / "PAUSE").exists()


def test_old_commands_are_refused_and_unknown_text_gets_the_help_list(tmp_path):
    n, sent, _, changes = run(tmp_path, [upd(1, "/pause", age=13 * 3600), upd(2, "hello there")])
    assert "more than 12 hours old" in sent[0] and "/status" in sent[1] and changes == [] and not (tmp_path / "PAUSE").exists()


def test_status_says_whether_posting_is_on_and_what_went_out(tmp_path):
    n, sent, _, _ = run(tmp_path, [upd(1, "/status")])
    assert "Posting is on" in sent[0] and "Nothing posted yet today" in sent[0]
    (tmp_path / "logs" / "posts.jsonl").write_text(json.dumps({"date": "2026-10-13", "item": "x", "app": "waypoint", "status": "published"}) + "\n")
    assert "Posted on: Instagram" in tc.status(tmp_path, DAY)


def test_command_with_bot_name_suffix_is_understood(tmp_path):
    _, sent, _, _ = run(tmp_path, [upd(1, "/pause@Arthvan_bot")])
    assert sent[0].startswith("⏸ Paused")
