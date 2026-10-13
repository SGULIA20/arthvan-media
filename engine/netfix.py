"""Workaround for a network path that resets TLS to some Google API address ranges (seen from the founder's network on
13 Oct 2026: us-central1-aiplatform / generativelanguage failed on 172.217.112-119.x while the same hostnames worked on other
Google addresses). For the listed hosts, if a quick TLS probe on the normal address fails, connect to a working Google
address instead; the hostname (SNI) stays the same, so certificates still verify. Re-probes every 5 minutes, so the direct
route is used again as soon as it works. Never active under tests or when NETFIX=0."""
import os
import socket
import ssl
import time

HOSTS = {"us-central1-aiplatform.googleapis.com", "generativelanguage.googleapis.com", "texttospeech.googleapis.com"}
DONOR = "oauth2.googleapis.com"        # reachable from the same network; Google fronts all its APIs from the same pool
_CAFILE = "/etc/ssl/cert.pem"
_orig = socket.getaddrinfo
_state = {"checked": 0.0, "use_fallback": False, "ips": []}


def _probe(host: str) -> bool:
    """True when a TLS handshake to the host's normal address works."""
    ctx = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()
    try:
        ip = _orig(host, 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        with socket.create_connection((ip, 443), timeout=5) as s, ctx.wrap_socket(s, server_hostname=host):
            return True
    except Exception:
        return False


def _fallback_ips() -> list:
    if not _state["ips"]:
        try:
            _state["ips"] = list(dict.fromkeys(a[4][0] for a in _orig(DONOR, 443, socket.AF_INET, socket.SOCK_STREAM)))
        except Exception:
            _state["ips"] = []
    return _state["ips"]


def use_fallback(host: str, now: float = None) -> bool:
    now = time.time() if now is None else now
    if now - _state["checked"] > 300:
        _state["use_fallback"] = not _probe(host) and bool(_fallback_ips())
        _state["checked"] = now
    return _state["use_fallback"]


def _patched(host, port, *args, **kwargs):
    if host in HOSTS and use_fallback(host):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in _fallback_ips()]
    return _orig(host, port, *args, **kwargs)


def install() -> bool:
    if os.environ.get("NETFIX") == "0" or "PYTEST_CURRENT_TEST" in os.environ or socket.getaddrinfo is _patched:
        return False
    socket.getaddrinfo = _patched
    return True


def reachable(host: str = "us-central1-aiplatform.googleapis.com") -> bool:
    """True when a TLS connection to the host works, directly or through the workaround."""
    install()
    ctx = ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()
    try:
        ip = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        with socket.create_connection((ip, 443), timeout=6) as s, ctx.wrap_socket(s, server_hostname=host):
            return True
    except Exception:
        return False
