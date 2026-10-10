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
