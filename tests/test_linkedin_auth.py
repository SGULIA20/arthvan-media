import os
import stat
import urllib.parse

import pytest

from engine import linkedin_auth as la


def test_authorize_url_asks_for_the_posting_scope_and_carries_state():
    url = la.authorize_url("CID", "http://localhost:3000/callback", "st4te")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert q["response_type"] == ["code"] and q["client_id"] == ["CID"] and q["state"] == ["st4te"]
    assert q["redirect_uri"] == ["http://localhost:3000/callback"]
    assert set(q["scope"][0].split()) == {"openid", "profile", "w_member_social"}


def test_exchange_code_posts_the_form_and_returns_the_token_fields():
    seen = {}

    def fake_post(url, form):
        seen.update(url=url, form=form)
        return {"access_token": "AT", "expires_in": 5184000}
    out = la.exchange_code("CID", "SECRET", "CODE", "http://localhost:3000/callback", post=fake_post)
    assert out == {"access_token": "AT", "expires_in": 5184000}
    assert seen["url"] == "https://www.linkedin.com/oauth/v2/accessToken"
    assert seen["form"]["grant_type"] == "authorization_code" and seen["form"]["code"] == "CODE"
    with pytest.raises(la.AuthError):
        la.exchange_code("CID", "SECRET", "CODE", "http://x", post=lambda u, f: {"error": "invalid_grant"})


def test_update_env_replaces_adds_and_keeps_everything_else_private(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# note\nIG_ACCESS_TOKEN=keepme\nLINKEDIN_ACCESS_TOKEN=\n")
    la.update_env(env, {"LINKEDIN_ACCESS_TOKEN": "new", "LINKEDIN_PERSON_URN": "urn:li:person:1"})
    lines = env.read_text().splitlines()
    assert "# note" in lines and "IG_ACCESS_TOKEN=keepme" in lines
    assert "LINKEDIN_ACCESS_TOKEN=new" in lines and "LINKEDIN_PERSON_URN=urn:li:person:1" in lines
    assert lines.count("LINKEDIN_ACCESS_TOKEN=new") == 1
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600


def test_person_urn_comes_from_the_openid_subject():
    assert la.person_urn({"sub": "abc123"}) == "urn:li:person:abc123"
    with pytest.raises(la.AuthError):
        la.person_urn({})
