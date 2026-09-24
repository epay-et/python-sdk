"""Client construction, key inspection, and environment fallbacks."""

from __future__ import annotations

import pytest

from epay import DEFAULT_BASE_URL, AsyncEpay, Epay, EpayConfigError, mode_from_api_key


def test_mode_from_api_key_maps_prefixes_and_tolerates_unknown():
    assert mode_from_api_key("sk_live_abc") == "live"
    assert mode_from_api_key("sk_test_abc") == "sandbox"
    assert mode_from_api_key("sk_future_abc") is None


def test_the_client_derives_mode_from_the_key_prefix():
    with Epay("sk_live_abc123") as epay:
        assert epay.mode == "live"
        assert epay.is_sandbox is False
    with Epay("sk_test_abc123") as epay:
        assert epay.is_sandbox is True


@pytest.mark.parametrize("key", ["", "   ", "pk_live_abc123"])
def test_the_client_rejects_a_missing_or_non_secret_key(key, monkeypatch):
    monkeypatch.delenv("EPAY_SECRET_KEY", raising=False)
    with pytest.raises(EpayConfigError):
        Epay(key)


def test_the_client_rejects_out_of_range_options():
    for kwargs in [{"timeout": 0}, {"timeout": -1}, {"max_retries": -1}]:
        with pytest.raises(EpayConfigError):
            Epay("sk_test_a", **kwargs)


def test_options_fall_back_to_environment_variables(monkeypatch):
    monkeypatch.setenv("EPAY_SECRET_KEY", "sk_test_from_env")
    monkeypatch.setenv("EPAY_BASE_URL", "https://staging.e-pay.et/v1")
    monkeypatch.setenv("EPAY_WEBHOOK_SECRET", "whsec_from_env")

    with Epay() as epay:
        assert epay.is_sandbox
        assert epay.base_url == "https://staging.e-pay.et/v1"
        assert epay.webhooks.configured


def test_a_trailing_slash_does_not_double_up(monkeypatch):
    monkeypatch.delenv("EPAY_BASE_URL", raising=False)
    with Epay("sk_test_a", base_url="https://api.e-pay.et/v1/") as epay:
        assert epay.base_url == "https://api.e-pay.et/v1"


def test_base_url_defaults_to_the_documented_root(monkeypatch):
    monkeypatch.delenv("EPAY_BASE_URL", raising=False)
    with Epay("sk_test_a") as epay:
        assert epay.base_url == DEFAULT_BASE_URL
    assert DEFAULT_BASE_URL == "https://api.e-pay.et/v1"


def test_repr_never_leaks_the_api_key():
    key = "sk_live_supersecretvalue1234"
    with Epay(key) as epay:
        assert "supersecretvalue" not in repr(epay)
        assert "sk_live_…1234" in repr(epay)

    rendered = repr(AsyncEpay(key))
    assert "supersecretvalue" not in rendered


def test_the_sync_client_works_as_a_context_manager():
    with Epay("sk_test_abc") as epay:
        assert isinstance(epay, Epay)


async def test_the_async_client_works_as_a_context_manager():
    async with AsyncEpay("sk_test_abc") as epay:
        assert isinstance(epay, AsyncEpay)
