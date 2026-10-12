import json

from radar import report


SNAP = {"date": "2026-10-19", "apps": {"scoremybiz": {"Khatabook": {"play": {"title": "Khatabook", "short": "Udhar khata, dues reminder", "about": "Collect dues faster."}, "youtube": [{"id": "x1", "title": "Diwali stock tips"}]}},
                                        "waypoint": {"Vent": {"play": {"title": "Vent", "short": "Say what you feel", "about": "Anonymous."}, "youtube": []}}}}


def test_ideas_section_is_added_when_gemini_answers(monkeypatch, tmp_path):
    prompts = []
    monkeypatch.setattr(report, "ask", lambda prompt, **kw: prompts.append(prompt) or "1. Lumi meets a sweet-shop owner...\n2. ...\n3. ...")
    md = report.render(SNAP, None, gemini=True)
    assert "**Three story ideas (Gemini):**" in md and "sweet-shop owner" in md
    assert len(prompts) == 2 and "Khatabook" in prompts[0] and "doctor" in prompts[0].lower()   # the no-doctor rule travels with the prompt
    assert "Vent" in prompts[1] and "Mira" in prompts[1]


def test_report_survives_a_gemini_failure(monkeypatch):
    from engine.gemini import GeminiError
    def boom(prompt, **kw): raise GeminiError("quota")
    monkeypatch.setattr(report, "ask", boom)
    md = report.render(SNAP, None, gemini=True)
    assert "| Theme |" in md and "ideas skipped" in md


def test_no_key_means_rules_only(monkeypatch):
    monkeypatch.setattr(report, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")))
    md = report.render(SNAP, None, gemini=False)
    assert "Gemini" not in md
