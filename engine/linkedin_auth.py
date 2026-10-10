"""One-time LinkedIn login (repeat about every 60 days).

python -m engine.linkedin_auth
Reads LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET from ~/arthvan-social/.env, opens LinkedIn in the browser,
catches the redirect on localhost:3000, then stores the token and your member id in the same file and as
GitHub secrets. The token is never printed.
"""
import http.server
import json
import os
import secrets
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import date
from pathlib import Path

from . import linkedin

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
SCOPES = "openid profile w_member_social"
REDIRECT = "http://localhost:3000/callback"
REPO = "SGULIA20/arthvan-media"
_CAFILE = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class AuthError(Exception):
    pass


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    q = urllib.parse.urlencode({"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
                                "state": state, "scope": SCOPES})
    return f"{AUTH_URL}?{q}"


def _post(url: str, form: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
            return json.loads(r.read())
    except Exception as e:
        raise AuthError(f"token request failed: {type(e).__name__}") from None


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str, post=_post) -> dict:
    res = post(TOKEN_URL, {"grant_type": "authorization_code", "code": code, "client_id": client_id,
                           "client_secret": client_secret, "redirect_uri": redirect_uri})
    if "access_token" not in res:
        raise AuthError(res.get("error_description") or res.get("error") or "LinkedIn returned no token")
    return {"access_token": res["access_token"], "expires_in": res.get("expires_in")}


def person_urn(info: dict) -> str:
    if not info.get("sub"):
        raise AuthError("LinkedIn did not return a member id")
    return f"urn:li:person:{info['sub']}"


def _read_env(path: Path) -> dict:
    out = {}
    for line in Path(path).read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def update_env(path, updates: dict) -> None:
    path = Path(path)
    lines = path.read_text().splitlines() if path.exists() else []
    for key, value in updates.items():
        for i, line in enumerate(lines):
            if line.startswith(key + "="):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def _wait_for_code(state: str, port: int = 3000, timeout: int = 300) -> str:
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state") == [state] and "code" in q:
                result["code"] = q["code"][0]
                body = b"<h2>Done. You can close this tab and return to Claude.</h2>"
            else:
                result["error"] = (q.get("error_description") or q.get("error") or ["state mismatch"])[0]
                body = b"<h2>Something went wrong. Return to Claude.</h2>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 5
    deadline = time.monotonic() + timeout
    while not result and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()
    if "code" not in result:
        raise AuthError(result.get("error", "timed out waiting for LinkedIn"))
    return result["code"]


def _gh(args: list, value: str = None) -> None:
    subprocess.run(["gh", *args, "--repo", REPO], input=value.encode() if value is not None else None, check=True)


def main(argv=None) -> int:
    env_path = Path(os.environ.get("ARTHVAN_ENV", Path.home() / "arthvan-social" / ".env"))
    env = _read_env(env_path)
    cid, secret = env.get("LINKEDIN_CLIENT_ID"), env.get("LINKEDIN_CLIENT_SECRET")
    if not cid or not secret:
        print(f"Put LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in {env_path} first.")
        return 1
    state = secrets.token_urlsafe(16)
    print("Opening LinkedIn in your browser. Log in and press Allow.")
    webbrowser.open(authorize_url(cid, REDIRECT, state))
    try:
        tok = exchange_code(cid, secret, _wait_for_code(state), REDIRECT)
        urn = person_urn(linkedin.userinfo(tok["access_token"]))
    except (AuthError, linkedin.LinkedInError) as e:
        print(f"Login failed: {e}")
        return 1
    today = date.today().isoformat()
    update_env(env_path, {"LINKEDIN_ACCESS_TOKEN": tok["access_token"], "LINKEDIN_PERSON_URN": urn,
                          "LINKEDIN_TOKEN_DATE": today})
    print(f"Saved the LinkedIn token (valid about {int(tok['expires_in'] or 0) // 86400} days) and your member id.")
    if "--no-github" not in (argv or sys.argv[1:]):
        _gh(["secret", "set", "LINKEDIN_ACCESS_TOKEN"], tok["access_token"])
        _gh(["secret", "set", "LINKEDIN_PERSON_URN"], urn)
        _gh(["variable", "set", "LINKEDIN_TOKEN_DATE", "--body", today])
        print("Stored LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN and LINKEDIN_TOKEN_DATE on GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
