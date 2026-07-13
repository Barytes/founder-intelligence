import pytest


@pytest.fixture(autouse=True)
def preserve_legacy_default_for_pre_l4_regression_tests(monkeypatch):
    """Legacy tests opt into the one-release compatibility path explicitly."""
    monkeypatch.setenv("FI_L4_LEGACY_FALLBACK", "1")
