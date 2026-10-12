from radar import comments

SNAP = {"date": "2026-10-19", "apps": {
    "scoremybiz": {"Khatabook": {"youtube": [{"id": "new1", "title": "Udhar vasool kaise karein"}, {"id": "old1", "title": "GST basics"}]},
                   "Vyapar": {"youtube": [{"id": "new2", "title": "Diwali stock planning"}]}},
    "waypoint": {"Vent": {"youtube": []}}}}
PREV = {"apps": {"scoremybiz": {"Khatabook": {"youtube": [{"id": "old1", "title": "GST basics"}]}}}}


def test_fresh_videos_come_first_and_each_gets_its_draft(monkeypatch):
    prompts = []
    monkeypatch.setattr(comments, "ask", lambda p, **k: prompts.append(p) or "1. Pehle chhote udhar wale ko yaad dilao.\n2. Count the shelf before you buy.\n3) Third")
    md = comments.render(SNAP, PREV)
    vids = comments.newest_videos(SNAP, "scoremybiz", PREV)
    assert [v["id"] for v in vids] == ["new1", "new2", "old1"]           # unseen first, then last week's
    assert "watch?v=new1" in md and "Pehle chhote udhar" in md and "Count the shelf" in md
    assert "**waypoint**" not in md                                       # nothing to comment on
    assert len(prompts) == 1 and "Hinglish" in prompts[0] and "never asks" in prompts[0]


def test_a_gemini_failure_leaves_a_note_not_a_crash(monkeypatch):
    from engine.gemini import GeminiError
    monkeypatch.setattr(comments, "ask", lambda p, **k: (_ for _ in ()).throw(GeminiError("quota")))
    md = comments.render(SNAP, PREV)
    assert "drafts skipped" in md


def test_split_handles_both_numbering_styles():
    assert comments._split("1. one\n2) two words\n\n3. three", 3) == ["one", "two words", "three"]
    assert comments._split("garbage", 2) == ["", ""]
