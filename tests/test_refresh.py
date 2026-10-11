from engine import instagram, refresh


def test_same_token_returned_is_success_and_prints_days_not_the_token(monkeypatch, capsys):
    monkeypatch.setattr(instagram, "refresh_token", lambda t: {"access_token": t, "expires_in": 5184000})
    assert refresh.main({"IG_ACCESS_TOKEN": "TOKEN-ABC"}) == 0
    out = capsys.readouterr().out
    assert "60 days" in out and "TOKEN-ABC" not in out


def test_a_different_token_fails_loudly_so_the_founder_is_told(monkeypatch, capsys):
    monkeypatch.setattr(instagram, "refresh_token", lambda t: {"access_token": "OTHER-XYZ", "expires_in": 5184000})
    assert refresh.main({"IG_ACCESS_TOKEN": "TOKEN-ABC"}) == 1
    out = capsys.readouterr().out
    assert "OTHER-XYZ" not in out and "TOKEN-ABC" not in out


def test_api_errors_and_missing_token_fail(monkeypatch):
    def boom(t):
        raise instagram.InstagramError("HTTP 400")
    monkeypatch.setattr(instagram, "refresh_token", boom)
    assert refresh.main({"IG_ACCESS_TOKEN": "t"}) == 1
    assert refresh.main({}) == 1


def test_a_token_younger_than_a_day_is_not_a_failure(monkeypatch, capsys):
    def young(t):
        raise instagram.InstagramError("HTTP 400: token must be at least 24 hours old")
    monkeypatch.setattr(instagram, "refresh_token", young)
    assert refresh.main({"IG_ACCESS_TOKEN": "t"}) == 0
    assert "too new" in capsys.readouterr().out


def test_linkedin_token_age_warns_from_fifty_days():
    from datetime import date
    today = date(2026, 12, 1)
    assert refresh.linkedin_age_problem({"LINKEDIN_TOKEN_DATE": "2026-10-20"}, today) is None      # 42 days
    assert "50" in refresh.linkedin_age_problem({"LINKEDIN_TOKEN_DATE": "2026-10-10"}, today)       # 52 days
    assert refresh.linkedin_age_problem({}, today) is None                                          # LinkedIn not set up
    assert "date" in refresh.linkedin_age_problem({"LINKEDIN_TOKEN_DATE": "soon"}, today).lower()


def test_main_fails_when_the_linkedin_token_is_old_even_if_instagram_is_fine(monkeypatch):
    from datetime import date
    monkeypatch.setattr(instagram, "refresh_token", lambda t: {"access_token": t, "expires_in": 5184000})
    env = {"IG_ACCESS_TOKEN": "t", "LINKEDIN_TOKEN_DATE": "2026-10-01"}
    assert refresh.main(env, today=date(2026, 12, 1)) == 1
    assert refresh.main(dict(env, LINKEDIN_TOKEN_DATE="2026-11-20"), today=date(2026, 12, 1)) == 0


def test_threads_refresh_runs_only_when_configured_and_flags_rotation(monkeypatch):
    from engine import threads
    monkeypatch.setattr(instagram, "refresh_token", lambda t: {"access_token": t, "expires_in": 5184000})
    monkeypatch.setattr(threads, "refresh_token", lambda t: {"access_token": t, "expires_in": 5184000})
    assert refresh.main({"IG_ACCESS_TOKEN": "a", "THREADS_ACCESS_TOKEN": "b"}) == 0
    monkeypatch.setattr(threads, "refresh_token", lambda t: {"access_token": "other", "expires_in": 1})
    assert refresh.main({"IG_ACCESS_TOKEN": "a", "THREADS_ACCESS_TOKEN": "b"}) == 1
    assert refresh.main({"IG_ACCESS_TOKEN": "a"}) == 0
