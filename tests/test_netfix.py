import socket

from engine import netfix


def test_fallback_addresses_replace_the_blocked_ones_only_for_listed_hosts(monkeypatch):
    monkeypatch.setattr(netfix, "_state", {"checked": 0.0, "use_fallback": False, "ips": ["142.250.1.1", "142.250.1.2"]})
    monkeypatch.setattr(netfix, "_probe", lambda host: False)                  # the direct route is broken
    monkeypatch.setattr(netfix, "_orig", lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.217.112.4", port))])
    out = netfix._patched("us-central1-aiplatform.googleapis.com", 443)
    assert [a[4][0] for a in out] == ["142.250.1.1", "142.250.1.2"]
    assert netfix._patched("example.com", 443)[0][4][0] == "172.217.112.4"      # other hosts are untouched


def test_a_working_direct_route_is_used_and_the_probe_is_repeated_only_every_five_minutes(monkeypatch):
    calls = []
    monkeypatch.setattr(netfix, "_state", {"checked": 0.0, "use_fallback": False, "ips": ["142.250.1.1"]})
    monkeypatch.setattr(netfix, "_probe", lambda host: calls.append(host) or True)
    assert netfix.use_fallback("h", now=1000.0) is False and netfix.use_fallback("h", now=1100.0) is False and len(calls) == 1
    monkeypatch.setattr(netfix, "_probe", lambda host: False)
    assert netfix.use_fallback("h", now=1400.0) is True                          # 300 s later: probed again, now broken


def test_no_donor_addresses_means_no_fallback(monkeypatch):
    monkeypatch.setattr(netfix, "_state", {"checked": 0.0, "use_fallback": False, "ips": []})
    monkeypatch.setattr(netfix, "_probe", lambda host: False)
    monkeypatch.setattr(netfix, "_fallback_ips", lambda: [])
    assert netfix.use_fallback("h", now=10.0) is False
