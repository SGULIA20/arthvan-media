from engine import story_hook as sh


def _st(vo, **kw):
    return {"id": "x", "lang": "en", "scenes": [{"vo": vo, "sub": vo}], **kw}


def test_greetings_and_introductions_are_refused_in_every_language():
    for vo in ("Hi. This is Imtiaz's story. Every March...", "Hi, I'm Lumi. Part three.", "नमस्ते। यह अनिल की कहानी है।",
               "હાય. આ ઇમ્તિયાઝની વાર્તા છે.", "வணக்கம். இது இம்ரானின் கதை."):
        assert sh.opening_problems(_st(vo)), vo
    assert sh.opening_problems(_st("Every March, Imtiaz's accountant asks one question: what do you own?")) == []
    assert sh.opening_problems(_st("Hi, Happy Dussehra!", occasion="dussehra")) == []          # a festival Reel may greet


def test_a_rewrite_is_kept_only_when_it_passes_the_checks():
    old = "Hi. This is Imtiaz's story. Every March his accountant asks him the same question."
    assert sh.check_rewrite(old, "What do you own? Every March, Imtiaz's accountant asks.") == []
    assert "a number that is not in the original" in sh.check_rewrite(old, "Imtiaz lost 500 rupees every March?")
    assert sh.check_rewrite(old, "Hi! Imtiaz here.")                                             # still a greeting
    assert "not in the original script" in sh.check_rewrite("नमस्ते। यह अनिल की कहानी है।", "Anil ki dukaan mein bill kahan hai?")


def test_rewrite_and_apply_change_voice_and_subtitles_and_mark_the_story():
    st = _st("Hi. This is Anil's story. A customer asked for a proper bill.")
    new, problems = sh.rewrite(st, ask=lambda prompt, max_tokens=600: "A customer asked Anil for a proper bill. He had none.")
    assert problems == []
    out = sh.apply(st, new)
    assert out["scenes"][0]["vo"] == out["scenes"][0]["sub"] == new and out["hook_rewritten"]
