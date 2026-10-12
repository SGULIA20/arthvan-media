"""Weekly Instagram token refresh. Exit 1 whenever a human has to look."""
import os
import subprocess
import sys
from datetime import date

from . import instagram, threads


LINKEDIN_WARN_DAYS = 50


def linkedin_age_problem(env, today: date):
    """LinkedIn self-serve tokens last about 60 days and cannot be refreshed by a program."""
    raw = env.get("LINKEDIN_TOKEN_DATE")
    if not raw:
        return None
    try:
        created = date.fromisoformat(raw)
    except ValueError:
        return f"LINKEDIN_TOKEN_DATE is not a date: {raw!r}"
    age = (today - created).days
    if age >= LINKEDIN_WARN_DAYS:
        return (f"LinkedIn token is {age} days old and expires at 60 (the {LINKEDIN_WARN_DAYS} day warning). "
                "Run python -m engine.linkedin_auth on your Mac to renew it.")
    return None


def secret_writer(env):
    """Returns a function(name, value) that updates a repository secret, or None when no PAT is configured.
    GITHUB_TOKEN cannot write secrets, so this needs a fine-grained PAT with 'Secrets: write' stored as ACTIONS_PAT."""
    pat, repo = env.get("ACTIONS_PAT"), env.get("GITHUB_REPOSITORY")
    if not pat or not repo:
        return None

    def write(name: str, value: str) -> None:
        r = subprocess.run(["gh", "secret", "set", name, "--repo", repo], input=value.encode(),
                           env={**os.environ, "GH_TOKEN": pat}, capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(f"gh secret set {name} failed")
    return write


def main(env=None, today=None, store_secret=None) -> int:
    env = os.environ if env is None else env
    store = store_secret or secret_writer(env)
    rc = _refresh_instagram(env, store)
    if env.get("THREADS_ACCESS_TOKEN"):
        rc = _refresh_threads(env, store) or rc
    problem = linkedin_age_problem(env, today or date.today())
    if problem:
        print(f"::error::{problem}")
        rc = 1
    return rc


def _store_or_fail(name: str, new_token: str, store) -> int:
    if store is None:
        print(f"::error::{name}: the platform returned a new token but ACTIONS_PAT is not set, so it cannot be stored. "
              "Add a fine-grained PAT with Secrets: write as the ACTIONS_PAT secret, or update the secret by hand.")
        return 1
    try:
        store(name, new_token)
    except Exception as e:
        print(f"::error::{name}: storing the new token failed: {type(e).__name__}")
        return 1
    print(f"{name}: new token stored")
    return 0


def _refresh_instagram(env, store=None) -> int:
    token = env.get("IG_ACCESS_TOKEN")
    if not token:
        print("::error::IG_ACCESS_TOKEN is not set")
        return 1
    try:
        out = instagram.refresh_token(token)
    except instagram.InstagramError as e:
        if "24 hours" in str(e):
            print("Token is too new to refresh (Instagram needs it to be a day old); nothing to do yet")
            return 0
        print(f"::error::token refresh failed: {e}")
        return 1
    if out.get("access_token") != token:
        return _store_or_fail("IG_ACCESS_TOKEN", out["access_token"], store)
    print(f"Token refreshed, valid for {int(out.get('expires_in', 0)) // 86400} days")
    return 0



def _refresh_threads(env, store=None) -> int:
    token = env["THREADS_ACCESS_TOKEN"]
    try:
        out = threads.refresh_token(token)
    except threads.ThreadsError as e:
        if "24 hours" in str(e):
            print("Threads token is too new to refresh; nothing to do yet")
            return 0
        print(f"::error::Threads token refresh failed: {e}")
        return 1
    if out.get("access_token") != token:
        return _store_or_fail("THREADS_ACCESS_TOKEN", out["access_token"], store)
    print(f"Threads token refreshed, valid for {int(out.get('expires_in', 0)) // 86400} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
