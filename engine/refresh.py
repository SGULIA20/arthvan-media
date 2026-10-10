"""Weekly Instagram token refresh. Exit 1 whenever a human has to look."""
import os
import sys

from . import instagram


def main(env=None) -> int:
    env = os.environ if env is None else env
    token = env.get("IG_ACCESS_TOKEN")
    if not token:
        print("::error::IG_ACCESS_TOKEN is not set")
        return 1
    try:
        out = instagram.refresh_token(token)
    except instagram.InstagramError as e:
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
