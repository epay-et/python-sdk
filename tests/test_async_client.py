"""The async client, against a scripted httpx transport.

The async surface shares its request builders and retry policy with the sync
one, so these tests target the awaiting, async iteration, and pool lifecycle
rather than re-covering validation.
"""

from __future__ import annotations

import httpx
import pytest
from conftest import SESSION, transaction

from epay import (
    AsyncEpay,
    EpayBadRequestError,
    EpayConnectionError,
    EpayNotFoundError,
    EpayRateLimitError,
    EpayTimeoutError,
    EpayValidationError,
)


async def test_initialize_normalizes_and_returns_the_session(async_client_factory):
    epay, calls = async_client_factory([{"json": SESSION}])

    session = await epay.payments.initialize(
        amount=250, currency_code="etb", customer_phone="0911234567"
    )

    assert session == SESSION
    assert calls.body() == {
        "amount": "250.00",
        "currencyCode": "ETB",
        "customerPhone": "+251911234567",
    }
    assert calls.header("x-idempotency-key")
    await epay.aclose()


async def test_initialize_validates_before_awaiting_a_request(async_client_factory):
    epay, calls = async_client_factory([])

    with pytest.raises(EpayValidationError):
        await epay.payments.initialize(
            amount="-1", currency_code="ETB", customer_phone="0911234567"
        )

    assert len(calls) == 0
    await epay.aclose()


async def test_verify_and_retrieve_hit_the_documented_paths(async_client_factory):
    epay, calls = async_client_factory([{"json": {"status": "completed"}}, {"json": transaction()}])

    await epay.payments.verify("PAB1")
    await epay.transactions.retrieve("PAB1")

    assert str(calls.url(0)) == "https://api.e-pay.et/v1/transactions/PAB1/verify"
    assert str(calls.url(1)) == "https://api.e-pay.et/v1/transactions/PAB1"
    await epay.aclose()


async def test_verify_reports_an_incomplete_transaction(async_client_factory):
    epay, _ = async_client_factory(
        [{"status": 400, "json": {"status": "error", "data": {"message": "not completed"}}}]
    )

    with pytest.raises(EpayBadRequestError, match="not completed"):
        await epay.payments.verify("PAB1")
    await epay.aclose()


async def test_cancel_resolves_on_204(async_client_factory):
    epay, calls = async_client_factory([{"status": 204}])

    assert await epay.payments.cancel("PAB1") is None
    assert str(calls.url()).endswith("/transactions/PAB1/cancel")
    await epay.aclose()


async def test_a_missing_transaction_raises_not_found(async_client_factory):
    epay, _ = async_client_factory(
        [{"status": 404, "json": {"status": "error", "data": {"message": "gone"}}}]
    )

    with pytest.raises(EpayNotFoundError):
        await epay.transactions.retrieve("nope")
    await epay.aclose()


async def test_async_iteration_walks_every_page(async_client_factory):
    epay, calls = async_client_factory(
        [
            {
                "json": {
                    "data": [transaction("P1"), transaction("P2")],
                    "nextCursor": "cur_1",
                    "hasMore": True,
                }
            },
            {"json": {"data": [transaction("P3")], "nextCursor": None, "hasMore": False}},
        ]
    )

    seen = []
    async for txn in await epay.transactions.list(status="completed"):
        seen.append(txn["reference"])

    assert seen == ["P1", "P2", "P3"]
    assert len(calls) == 2
    assert calls.url(1).params["cursor"] == "cur_1"
    assert calls.url(1).params["status"] == "completed"
    await epay.aclose()


async def test_async_to_list_honours_the_limit(async_client_factory):
    epay, calls = async_client_factory(
        [
            {
                "json": {
                    "data": [transaction("P1"), transaction("P2")],
                    "nextCursor": "cur_1",
                    "hasMore": True,
                }
            },
            {"json": {"data": [transaction("P3")], "nextCursor": "cur_2", "hasMore": True}},
        ]
    )

    page = await epay.transactions.list()
    collected = await page.to_list(limit=3)

    assert [t["reference"] for t in collected] == ["P1", "P2", "P3"]
    assert len(calls) == 2
    await epay.aclose()


async def test_async_next_page_returns_none_on_the_last_page(async_client_factory):
    epay, _ = async_client_factory(
        [{"json": {"data": [transaction("P1")], "nextCursor": None, "hasMore": False}}]
    )

    page = await epay.transactions.list()
    assert await page.next_page() is None
    assert len(page) == 1
    await epay.aclose()


async def test_providers_are_unwrapped(async_client_factory):
    epay, _ = async_client_factory(
        [
            {
                "json": {
                    "data": [
                        {
                            "providerCode": "telebirr",
                            "providerName": "Telebirr",
                            "providerCategory": "mobile_money",
                            "flowCode": "ussd",
                            "isEnabled": True,
                        },
                        {
                            "providerCode": "awash_bank",
                            "providerName": "Awash",
                            "providerCategory": "bank",
                            "flowCode": "mobile_banking",
                            "isEnabled": False,
                        },
                    ]
                }
            }
        ]
    )

    enabled = await epay.payment_providers.list_enabled()
    assert [p["providerCode"] for p in enabled] == ["telebirr"]
    await epay.aclose()


async def test_a_429_is_retried(async_client_factory):
    epay, calls = async_client_factory(
        [{"status": 429, "headers": {"retry-after": "0"}}, {"json": transaction()}],
        max_retries=1,
    )

    assert (await epay.transactions.retrieve("P1"))["reference"] == "PAB12CD3420260813"
    assert len(calls) == 2
    await epay.aclose()


async def test_the_rate_limit_error_surfaces_after_the_budget(async_client_factory):
    epay, calls = async_client_factory(
        [
            {"status": 429, "headers": {"retry-after": "0"}},
            {"status": 429, "headers": {"retry-after": "0"}},
        ],
        max_retries=1,
    )

    with pytest.raises(EpayRateLimitError):
        await epay.transactions.retrieve("P1")
    assert len(calls) == 2
    await epay.aclose()


async def test_a_transport_error_is_retried_then_surfaced():
    attempts = {"count": 0}

    def handler(request):
        attempts["count"] += 1
        raise httpx.ConnectError("connection refused", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with AsyncEpay("sk_test_abc", http_client=http_client, max_retries=1) as epay:
        with pytest.raises(EpayConnectionError):
            await epay.transactions.retrieve("P1")

    assert attempts["count"] == 2
    await http_client.aclose()


async def test_a_timeout_maps_to_the_timeout_error():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with AsyncEpay("sk_test_abc", http_client=http_client, max_retries=0) as epay:
        with pytest.raises(EpayTimeoutError, match="timed out"):
            await epay.transactions.retrieve("P1")

    await http_client.aclose()


async def test_the_escape_hatch_works_on_the_async_client(async_client_factory):
    epay, calls = async_client_factory([{"json": {"ok": True}}])

    data = await epay.request("GET", "/some/future/endpoint", params={"limit": 10})

    assert data == {"ok": True}
    assert calls.url().params["limit"] == "10"
    await epay.aclose()


async def test_a_supplied_async_client_is_not_closed_by_the_sdk():
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    epay = AsyncEpay("sk_test_abc", http_client=http_client)
    await epay.aclose()

    assert not http_client.is_closed, "the SDK must not close a pool it did not create"
    await http_client.aclose()
