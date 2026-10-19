from engine import comment_drafts as cd
from engine import tg_commands as tc

POST = "Most companies think they need to improve everything. In reality, they only need to improve one thing: the bottleneck."


def test_prompt_carries_voice_rules_and_the_post():
    p = cd.prompt(POST)
    assert "Under 60 words" in p and "Great post" in p and POST in p and "ADD:" in p and "ASK:" in p


def test_empty_or_tiny_post_returns_usage_without_asking():
    calls = []
    assert cd.drafts("", ask=lambda *a, **k: calls.append(1)) == cd.USAGE
    assert cd.drafts("   short", ask=lambda *a, **k: calls.append(1)) == cd.USAGE
    assert calls == []


def test_drafts_return_the_model_answer_and_a_failure_is_a_friendly_message():
    assert cd.drafts(POST, ask=lambda prompt, **k: "ADD:\nx\n\nASK:\ny?\n") == "ADD:\nx\n\nASK:\ny?"

    def boom(prompt, **k):
        raise RuntimeError("quota")
    assert cd.drafts(POST, ask=boom).startswith("Could not draft right now (RuntimeError: quota)")


def test_comment_command_hands_the_pasted_text_to_the_drafter(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cd, "drafts", lambda text: seen.append(text) or "two drafts")
    assert tc.answer("/comment " + POST, tmp_path, None) == "two drafts"
    assert seen[0].strip() == POST
    monkeypatch.undo()
    assert tc.answer("/comment", tmp_path, None) == cd.USAGE
    assert "/comment" in tc.HELP
