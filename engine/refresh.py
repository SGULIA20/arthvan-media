"""Weekly Instagram token refresh. Exit 1 whenever a human has to look."""
import os
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


def main(env=None, today=None) -> int:
    env = os.environ if env is None else env
    rc = _refresh_instagram(env)
    if env.get("THREADS_ACCESS_TOKEN"):
        rc = _refresh_threads(env) or rc
    problem = linkedin_age_problem(env, today or date.today())
    if problem:
        print(f"::error::{problem}")
        rc = 1
    return rc


def _refresh_instagram(env) -> int:
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
        print("::error::Instagram returned a different token. Generate a new token in the Meta developer "
              "dashboard and update the IG_ACCESS_TOKEN secret.")
        return 1
    print(f"Token refreshed, valid for {int(out.get('expires_in', 0)) // 86400} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def _refresh_threads(env) -> int:
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
        print("::error::Threads returned a different token. Generate a new one in the Meta dashboard and update THREADS_ACCESS_TOKEN.")
        return 1
    print(f"Threads token refreshed, valid for {int(out.get('expires_in', 0)) // 86400} days")
    return 0
