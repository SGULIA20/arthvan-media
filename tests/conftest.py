import pytest


@pytest.fixture(autouse=True)
def _no_model_keys(monkeypatch):
    """No test may reach a paid model: the LinkedIn evening run now tries a live post on every posting day."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
