import json

import pytest

from engine import translator as tr

BASE = {"id": "x-en", "app": "scoremybiz", "title": "Title", "caption": "Cap",
        "scenes": [{"vo": "In the free month she fills four things.", "card": "Card"}, {"vo": "Done in a minute."}, {"vo": "ScoreMyBiz. Free."}]}


def fake(answer):
    calls = []
    def ask(prompt, **kw): calls.append(prompt); return answer if isinstance(answer, str) else answer(len(calls))
    ask.calls = calls
    return ask


GOOD = json.dumps({"title": "T", "caption": "C", "scenes": [{"vo": "En el mes gratis rellena cuatro cosas.", "card": "Tarjeta"}, {"vo": "Hecho en un minuto."}, {"vo": "ScoreMyBiz. Gratis."}]})


def test_a_good_translation_is_accepted_and_marked_as_a_machine_draft():
    t = tr.translate_story(BASE, "es", fake("```json\n" + GOOD + "\n```"))
    assert t["machine_translated"] is True and len(t["scenes"]) == 3 and t["scenes"][0]["card"] == "Tarjeta"


def test_changed_numbers_a_lost_scene_or_a_missing_card_reject_the_translation():
    base = dict(BASE, scenes=[{"vo": "She fills 4 things."}, {"vo": "Done."}])
    bad = json.dumps({"title": "T", "caption": "C", "scenes": [{"vo": "Rellena 5 cosas."}, {"vo": "Hecho."}]})
    with pytest.raises(tr.TranslationRejected, match="numbers changed"):
        tr.translate_story(base, "es", fake(bad))
    short = json.dumps({"title": "T", "caption": "C", "scenes": [{"vo": "Hola."}]})
    with pytest.raises(tr.TranslationRejected, match="1 scenes, expected 3"):
        tr.translate_story(BASE, "es", fake(short))
    nocard = json.dumps({"title": "T", "caption": "C", "scenes": [{"vo": "En el mes gratis rellena cuatro cosas."}, {"vo": "Hecho en un minuto."}, {"vo": "ScoreMyBiz. Gratis."}]})
    with pytest.raises(tr.TranslationRejected, match="card missing"):
        tr.translate_story(BASE, "es", fake(nocard))


def test_it_retries_once_with_the_model_and_native_digits_count_as_the_same_number():
    base = dict(BASE, scenes=[{"vo": "She fills 4 things."}])
    answers = {1: json.dumps({"title": "T", "caption": "C", "scenes": [{"vo": "Rellena 9 cosas."}]}),
               2: json.dumps({"title": "T", "caption": "C", "scenes": [{"vo": "تملأ ٤ أشياء."}]})}      # Arabic-Indic digit four
    ask = fake(lambda n: answers[n])
    assert tr.translate_story(base, "ar", ask)["scenes"][0]["vo"].startswith("تملأ") and len(ask.calls) == 2


def test_the_end_card_translation_must_keep_its_n_placeholder(tmp_path):
    ok = json.dumps({"end_line": "30 días gratis", "link_in_bio": "Enlace en la bio", "languages_phrase": "Disponible en {n} idiomas", "money_disclaimer": "Cifras de ejemplo."})
    cfg = {"end_line": "Free for 30 days", "languages_phrase": "Works in {n} languages", "money_disclaimer": "Example figures."}
    assert tr.translate_end_card(cfg, "es", fake(ok))["languages_phrase"] == "Disponible en {n} idiomas"
    with pytest.raises(tr.TranslationRejected):
        tr.translate_end_card(cfg, "es", fake(ok.replace("{n}", "25")))


def test_ensure_files_writes_the_translation_once_and_reuses_it(tmp_path):
    ok_end = json.dumps({"end_line": "x", "link_in_bio": "y", "languages_phrase": "z {n}", "money_disclaimer": "m"})
    answers = iter([ok_end, GOOD])
    ask = lambda prompt, **kw: next(answers)
    cfg = {"end_line": "Free", "languages_phrase": "Works in {n}", "money_disclaimer": "m"}
    p = tr.ensure_files(BASE, "scoremybiz", cfg, "es", tmp_path, ask)
    assert p == tmp_path / "content" / "translations" / "es" / "x-en.json" and json.loads(p.read_text())["machine_translated"] is True
    assert json.loads((tmp_path / "content" / "end_card" / "es.json").read_text())["scoremybiz"]["languages_phrase"] == "z {n}"
    assert tr.ensure_files(BASE, "scoremybiz", cfg, "es", tmp_path, lambda *a, **k: 1 / 0) == p          # nothing is asked again
