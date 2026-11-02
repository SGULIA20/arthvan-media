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


def test_status_still_says_nothing_posted_after_only_the_personal_post(tmp_path):
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "logs" / "posts.jsonl").write_text('{"date": "2026-10-13", "channel": "linkedin_personal", "item": "toc", "status": "published", "id": "u"}\n')
    t = tc.status(tmp_path, DAY)
    assert "Nothing posted yet today" in t and "LinkedIn personal post: out (toc)." in t


def _video_update(uid, size=5_000_000, caption="/xray canwe.ai hook"):
    return {"update_id": uid, "message": {"chat": {"id": 42}, "date": int(time.time()), "caption": caption,
                                           "video": {"file_id": "F1", "file_size": size, "mime_type": "video/mp4"}}}


def test_a_reel_video_gets_an_xray_and_is_confirmed_before_the_slow_part(tmp_path):
    sent, confirmed, seen = [], [], []
    def call(token, method, body):
        if "offset" in body: confirmed.append(body["offset"]); return {"result": []}
        return {"result": [_video_update(9)]}
    def xr(cfg, m, root, call=None, change=None):
        seen.append(confirmed[:]); return "🎬 Reel X-ray\n\nHOOK: ..."
    n = tc.poll(CFG, tmp_path, call=call, send=lambda cfg, t: sent.append(t), change=lambda *a: None, day=DAY, xray_fn=xr)
    assert n == 1 and seen == [[10]] and sent[0].startswith("🎬 Got the Reel") and sent[1].startswith("🎬 Reel X-ray")


def test_xray_reply_saves_the_breakdown_and_passes_the_note(tmp_path):
    changes, notes = [], []
    def fetch(cfg, fid, out, call): out.write_bytes(b"mp4"); return out
    def analyse(path, note): notes.append(note); return "HOOK: a question in 2 seconds"
    reply = tc.xray_reply(CFG, _video_update(1)["message"], tmp_path, call=None, change=lambda root, add, rm, msg: changes.append(add),
                          analyse=analyse, fetch=fetch)
    assert reply.startswith("🎬 Reel X-ray") and notes == ["canwe.ai hook"]
    saved = list((tmp_path / "logs" / "xray").glob("*.md"))
    assert len(saved) == 1 and "a question in 2 seconds" in saved[0].read_text() and changes[0][0].startswith("logs/xray/")


def test_xray_refuses_a_video_too_big_for_the_bot(tmp_path):
    reply = tc.xray_reply(CFG, _video_update(1, size=60_000_000)["message"], tmp_path, call=None, change=lambda *a: None,
                          analyse=lambda p, n: "x", fetch=lambda *a: None)
    assert "over 20 MB" in reply


def test_xray_upload_and_answer_with_a_fake_gemini(tmp_path):
    from engine import xray
    v = tmp_path / "r.mp4"; v.write_bytes(b"x" * 10)
    calls = []
    def req(url, data=None, headers=None, method="GET", timeout=180):
        calls.append(url)
        if url.endswith("/upload/v1beta/files"):
            return {"X-Goog-Upload-URL": "https://up/1"}, b""
        if url == "https://up/1":
            return {}, json.dumps({"file": {"name": "files/a", "uri": "https://f/a", "state": "ACTIVE", "mimeType": "video/mp4"}}).encode()
        return {}, json.dumps({"candidates": [{"content": {"parts": [{"text": "1. HOOK: big question"}]}}]}).encode()
    assert xray.analyse(v, "note", key="k", req=req) == "1. HOOK: big question" and calls[-1].endswith(":generateContent")
