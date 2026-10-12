"""One-time YouTube authorisation per channel (SGLearning, Arthvan).

python -m engine.youtube_auth sglearning|arthvan
Reads YT_CLIENT_ID / YT_CLIENT_SECRET from ~/arthvan-social/.env, opens Google's consent page, catches the
redirect on localhost:3001, stores YT_<KEY>_REFRESH_TOKEN in the same file and as a GitHub secret. Never printed.
"""
import http.server, json, os, secrets, ssl, subprocess, sys, time, urllib.parse, urllib.request, webbrowser
from pathlib import Path

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
REDIRECT = "http://localhost:3001/callback"
REPO = "SGULIA20/arthvan-media"
_CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if os.path.exists("/etc/ssl/cert.pem") else ssl.create_default_context()


def authorize_url(client_id: str, state: str) -> str:
    return AUTH + "?" + urllib.parse.urlencode({"client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code",
                                                "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state})


def exchange(client_id, client_secret, code) -> dict:
    req = urllib.request.Request(TOKEN, data=urllib.parse.urlencode({"code": code, "client_id": client_id, "client_secret": client_secret,
                                 "redirect_uri": REDIRECT, "grant_type": "authorization_code"}).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
        return json.loads(r.read())


def channel_name(access: str) -> str:
    req = urllib.request.Request("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true", headers={"Authorization": "Bearer " + access})
    with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
        items = json.loads(r.read()).get("items", [])
    return items[0]["snippet"]["title"] if items else "?"


def wait_code(state: str, timeout=300) -> str:
    got = {}
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got["code"] = q.get("code", [None])[0] if q.get("state") == [state] else None
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(b"<h2>Done. Return to Claude.</h2>")
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 3001), H); srv.timeout = 5; end = time.monotonic() + timeout
    while "code" not in got and time.monotonic() < end: srv.handle_request()
    srv.server_close()
    if not got.get("code"): raise SystemExit("no authorisation code received")
    return got["code"]


def update_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text().splitlines(); done = False
    for i, l in enumerate(lines):
        if l.startswith(key + "="): lines[i] = f"{key}={value}"; done = True
    if not done: lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n"); os.chmod(path, 0o600)


def main() -> int:
    key = (sys.argv[1] if len(sys.argv) > 1 else "").upper()
    if key not in ("SGLEARNING", "ARTHVAN"):
        print("usage: python -m engine.youtube_auth sglearning|arthvan"); return 1
    env_path = Path.home() / "arthvan-social" / ".env"
    env = {l.split("=", 1)[0]: l.split("=", 1)[1] for l in env_path.read_text().splitlines() if "=" in l and not l.startswith("#")}
    cid, sec = env.get("YT_CLIENT_ID"), env.get("YT_CLIENT_SECRET")
    if not cid or not sec:
        print("Put YT_CLIENT_ID and YT_CLIENT_SECRET in ~/arthvan-social/.env first"); return 1
    state = secrets.token_urlsafe(12)
    print(f"Opening Google. Sign in, CHOOSE THE CHANNEL for {key.title()} when asked, and allow.")
    webbrowser.open(authorize_url(cid, state))
    tok = exchange(cid, sec, wait_code(state))
    if "refresh_token" not in tok:
        print("Google did not return a refresh token; remove the app at myaccount.google.com/permissions and retry"); return 1
    name = channel_name(tok["access_token"])
    secret = f"YT_{key}_REFRESH_TOKEN"
    update_env(env_path, secret, tok["refresh_token"])
    subprocess.run(["gh", "secret", "set", secret, "--repo", REPO], input=tok["refresh_token"].encode(), check=True)
    for k, v in (("YT_CLIENT_ID", cid), ("YT_CLIENT_SECRET", sec)):
        subprocess.run(["gh", "secret", "set", k, "--repo", REPO], input=v.encode(), check=True)
    print(f"Authorised channel: {name}. Stored {secret} locally and on GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
