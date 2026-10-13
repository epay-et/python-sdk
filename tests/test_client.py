"""The sync client, against a scripted httpx transport."""

from __future__ import annotations

import httpx
import pytest
from conftest import SESSION, transaction

from epay import (
    Epay,
    EpayAuthenticationError,
    EpayBadRequestError,
    EpayConnectionError,
    EpayNotFoundError,
    EpayPermissionDeniedError,
    EpayRateLimitError,
    EpayServerError,
    EpayTimeoutError,
    EpayValidationError,
)

# --- initialize -------------------------------------------------------------


def test_initialize_posts_to_the_documented_path(client_factory):
    epay, calls = client_factory([{"json": SESSION}])

    session = epay.payments.initialize(
        amount="250.00",
        currency_code="ETB",
        customer_phone="+251911234567",
        merchant_reference="order_123",
    )

    assert session == SESSION
    assert len(calls) == 1
    assert calls.calls[0].method == "POST"
    assert str(calls.url()) == "https://api.epayethiopia.com/v1/transactions/initialize"
    assert calls.header("authorization") == "Bearer sk_test_0123456789abcdef"
    assert calls.header("content-type") == "application/json"
    assert calls.header("user-agent").startswith("epay-python/")


def test_initialize_normalizes_amount_currency_and_phone(client_factory):
    epay, calls = client_factory([{"json": SESSION}])

    epay.payments.initialize(amount=250, currency_code="etb", customer_phone="0911234567")

    assert calls.body() == {
        "amount": "250.00",
        "currencyCode": "ETB",
        "customerPhone": "+251911234567",
    }


def test_initialize_omits_optional_fields_not_set(client_factory):
    epay, calls = client_factory([{"json": SESSION}])

    epay.payments.initialize(
        amount="10.00",
        currency_code="ETB",
        customer_phone="0911234567",
        email="abebe@example.com",
        return_url="https://store.example/done",
    )

    body = calls.body()
    assert body["email"] == "abebe@example.com"
    assert body["returnUrl"] == "https://store.example/done"
    for absent in ("merchantReference", "firstName", "lastName", "callbackUrl"):
        assert absent not in body, "unset fields should be absent, not null"


def test_initialize_sends_the_caller_idempotency_key(client_factory):
    epay, calls = client_factory([{"json": SESSION}])

    epay.payments.initialize(
        amount="10.00",
        currency_code="ETB",
        customer_phone="0911234567",
        idempotency_key="order_123",
    )

    assert calls.header("x-idempotency-key") == "order_123"


def test_initialize_generates_an_idempotency_key_when_omitted(client_factory):
    epay, calls = client_factory([{"json": SESSION}])

    epay.payments.initialize(amount="10.00", currency_code="ETB", customer_phone="0911234567")

    key = calls.header("x-idempotency-key")
    assert key and key.startswith("epay_") and len(key) > 12


def test_initialize_validates_before_spending_a_request(client_factory):
    epay, calls = client_factory([])

    with pytest.raises(EpayValidationError):
        epay.payments.initialize(amount="-1", currency_code="ETB", customer_phone="0911234567")
    with pytest.raises(EpayValidationError):
        epay.payments.initialize(amount="1.00", currency_code="ETB", customer_phone="123")
    with pytest.raises(EpayValidationError):
        epay.payments.initialize(
            amount="1.00",
            currency_code="ETB",
            customer_phone="0911234567",
            idempotency_key="x" * 256,
        )

    assert len(calls) == 0, "no request should reach the network"


def test_initialize_surfaces_a_missing_payment_source(client_factory):
    epay, _ = client_factory(
        [
            {
                "status": 404,
                "json": {"status": "error", "data": {"message": "No payment source found"}},
            }
        ]
    )

    with pytest.raises(EpayNotFoundError, match="No payment source found"):
        epay.payments.initialize(amount="1.00", currency_code="ETB", customer_phone="0911234567")


# --- verify and cancel ------------------------------------------------------


def test_verify_returns_the_receipt(client_factory):
    receipt = {
        "reference": "PAB12CD3420260813",
        "merchantReference": "order_123",
        "status": "completed",
        "amount": "250.00",
        "serviceFee": "7.50",
        "currencyCode": "ETB",
        "paymentMethod": "telebirr",
        "customer": {
            "name": "Abebe Bikila",
            "email": "abebe@example.com",
            "phone": "+251911234567",
        },
        "paidAt": "2026-08-13T11:47:00.000Z",
        "createdAt": "2026-08-13T11:30:00.000Z",
    }
    epay, calls = client_factory([{"json": receipt}])

    result = epay.payments.verify("PAB12CD3420260813")

    assert (
        str(calls.url()) == "https://api.epayethiopia.com/v1/transactions/PAB12CD3420260813/verify"
    )
    assert result["serviceFee"] == "7.50"
    assert result["customer"]["name"] == "Abebe Bikila"


def test_verify_reports_an_incomplete_transaction(client_factory):
    epay, _ = client_factory(
        [
            {
                "status": 400,
                "json": {
                    "status": "error",
                    "data": {"message": "Transaction is not completed. Current status: pending"},
                },
            }
        ]
    )

    with pytest.raises(EpayBadRequestError, match="Current status: pending"):
        epay.payments.verify("PAB1")


def test_cancel_resolves_on_204(client_factory):
    epay, calls = client_factory([{"status": 204}])

    assert epay.payments.cancel("PAB12CD3420260813") is None
    assert calls.calls[0].method == "POST"
    assert (
        str(calls.url()) == "https://api.epayethiopia.com/v1/transactions/PAB12CD3420260813/cancel"
    )


def test_cancel_is_never_retried(client_factory):
    epay, calls = client_factory([{"status": 500}], max_retries=3)

    with pytest.raises(EpayServerError):
        epay.payments.cancel("PAB1")

    assert len(calls) == 1, "a non-idempotent POST must be attempted exactly once"


def test_references_are_url_encoded(client_factory):
    epay, calls = client_factory([{"json": {}}])
    epay.transactions.retrieve("PAB 1/2")
    assert str(calls.url()) == "https://api.epayethiopia.com/v1/transactions/PAB%201%2F2"


def test_an_empty_reference_is_rejected_locally(client_factory):
    epay, calls = client_factory([])
    with pytest.raises(EpayValidationError):
        epay.transactions.retrieve("  ")
    with pytest.raises(EpayValidationError):
        epay.payments.verify("")
    assert len(calls) == 0


# --- transactions -----------------------------------------------------------


def test_list_builds_the_documented_query(client_factory):
    epay, calls = client_factory([{"json": {"data": [], "nextCursor": None, "hasMore": False}}])

    epay.transactions.list(
        status="completed", currency="etb", from_date="2026-08-01", to_date="2026-08-31"
    )

    params = calls.url().params
    assert calls.url().path == "/v1/transactions"
    assert params["status"] == "completed"
    assert params["currency"] == "ETB"
    assert params["from"] == "2026-08-01"
    assert params["to"] == "2026-08-31"


def test_list_accepts_date_objects(client_factory):
    from datetime import date

    epay, calls = client_factory([{"json": {"data": [], "nextCursor": None, "hasMore": False}}])
    epay.transactions.list(from_date=date(2026, 8, 1), to_date=date(2026, 8, 31))

    assert calls.url().params["from"] == "2026-08-01"
    assert calls.url().params["to"] == "2026-08-31"


def test_list_rejects_an_inverted_range_and_unknown_status(client_factory):
    epay, calls = client_factory([])

    with pytest.raises(EpayValidationError):
        epay.transactions.list(from_date="2026-08-31", to_date="2026-08-01")
    with pytest.raises(EpayValidationError):
        epay.transactions.list(status="expired")

    assert len(calls) == 0


def test_a_page_exposes_its_own_data_without_fetching_more(client_factory):
    epay, calls = client_factory(
        [{"json": {"data": [transaction()], "nextCursor": "cur_1", "hasMore": True}}]
    )

    page = epay.transactions.list()

    assert len(page.data) == 1
    assert page.has_more is True
    assert page.next_cursor == "cur_1"
    assert len(calls) == 1
    assert "has_more=True" in repr(page)


def test_iterating_a_page_walks_every_following_page(client_factory):
    epay, calls = client_factory(
        [
            {
                "json": {
                    "data": [transaction("P1"), transaction("P2")],
                    "nextCursor": "cur_1",
                    "hasMore": True,
                }
            },
            {"json": {"data": [transaction("P3")], "nextCursor": "cur_2", "hasMore": True}},
            {"json": {"data": [transaction("P4")], "nextCursor": None, "hasMore": False}},
        ]
    )

    seen = [t["reference"] for t in epay.transactions.list(status="completed")]

    assert seen == ["P1", "P2", "P3", "P4"]
    assert len(calls) == 3
    # The cursor advances while the filter persists across pages.
    assert "cursor" not in calls.url(0).params
    assert calls.url(1).params["cursor"] == "cur_1"
    assert calls.url(2).params["cursor"] == "cur_2"
    for index in range(3):
        assert calls.url(index).params["status"] == "completed"


def test_to_list_stops_fetching_once_the_limit_is_reached(client_factory):
    epay, calls = client_factory(
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

    collected = epay.transactions.list().to_list(limit=3)

    assert [t["reference"] for t in collected] == ["P1", "P2", "P3"]
    assert len(calls) == 2, "should not fetch a page it does not need"


def test_pages_yields_page_objects(client_factory):
    epay, _ = client_factory(
        [
            {"json": {"data": [transaction("P1")], "nextCursor": "cur_1", "hasMore": True}},
            {"json": {"data": [transaction("P2")], "nextCursor": None, "hasMore": False}},
        ]
    )

    sizes = [len(page) for page in epay.transactions.list().pages()]
    assert sizes == [1, 1]


def test_timeline_returns_events_in_order(client_factory):
    epay, calls = client_factory(
        [
            {
                "json": {
                    "reference": "PFF98AB1220260812",
                    "events": [
                        {
                            "eventType": "session_created",
                            "occurredAt": "2026-08-12T09:15:00.000Z",
                            "errorCode": None,
                            "errorMessage": None,
                        },
                        {
                            "eventType": "payment_failed",
                            "occurredAt": "2026-08-12T09:18:44.000Z",
                            "errorCode": "INSUFFICIENT_FUNDS",
                            "errorMessage": "no balance",
                        },
                    ],
                }
            }
        ]
    )

    timeline = epay.transactions.timeline("PFF98AB1220260812")

    assert str(calls.url()).endswith("/transactions/PFF98AB1220260812/timeline")
    assert len(timeline["events"]) == 2
    assert timeline["events"][1]["errorCode"] == "INSUFFICIENT_FUNDS"


# --- payment providers ------------------------------------------------------


def test_providers_are_unwrapped_from_the_envelope(client_factory):
    epay, calls = client_factory(
        [
            {
                "json": {
                    "data": [
                        {"providerCode": "telebirr", "providerName": "Telebirr", "flowCode": "ussd"}
                    ]
                }
            }
        ]
    )

    providers = epay.payment_providers.list()

    assert str(calls.url()) == "https://api.epayethiopia.com/v1/payment-providers/list"
    assert providers[0]["providerCode"] == "telebirr"


PROVIDERS = {
    "data": [
        {
            "providerCode": "TELEBIRR",
            "providerName": "TeleBirr",
            "providerCategory": "wallet",
            "flows": [
                {"flowCode": "USSD", "isDefault": True, "supportsDirectPayment": True},
                {"flowCode": "SMS_OTP", "isDefault": False, "supportsDirectPayment": False},
            ],
        },
        {
            "providerCode": "CBE",
            "providerName": "CBE",
            "providerCategory": "bank",
            "flows": [{"flowCode": "QR", "isDefault": True, "supportsDirectPayment": False}],
        },
    ]
}


def test_get_all_returns_providers_with_grouped_flows(client_factory):
    epay, calls = client_factory([{"json": PROVIDERS}])

    providers = epay.payment_providers.get_all()

    assert str(calls.url()) == "https://api.epayethiopia.com/v1/payment-providers"
    assert [f["flowCode"] for f in providers[0]["flows"]] == ["USSD", "SMS_OTP"]


def test_list_for_direct_payment_keeps_only_direct_flows(client_factory):
    epay, _ = client_factory([{"json": PROVIDERS}])

    providers = epay.payment_providers.list_for_direct_payment()

    assert [(p["providerCode"], [f["flowCode"] for f in p["flows"]]) for p in providers] == [
        ("TELEBIRR", ["USSD"])
    ]


def test_list_enabled_is_deprecated_and_returns_every_provider(client_factory):
    epay, _ = client_factory([{"json": PROVIDERS}])

    with pytest.warns(DeprecationWarning, match="list_enabled"):
        providers = epay.payment_providers.list_enabled()

    assert [p["providerCode"] for p in providers] == ["TELEBIRR", "CBE"]


def test_a_missing_permission_surfaces_as_permission_denied(client_factory):
    epay, _ = client_factory(
        [
            {
                "status": 403,
                "json": {
                    "statusCode": 403,
                    "message": "Missing get_platform_payment_provider permission",
                    "error": "Forbidden",
                },
            }
        ]
    )

    with pytest.raises(EpayPermissionDeniedError, match="get_platform_payment_provider"):
        epay.payment_providers.get_all()


def test_an_empty_provider_envelope_yields_an_empty_list(client_factory):
    epay, _ = client_factory([{"status": 204}])
    assert epay.payment_providers.list() == []


# --- direct payment, SMS link, receipt --------------------------------------

DIRECT = {
    "reference": "A3BX72KP",
    "status": "pending",
    "chargeAmount": "250.00",
    "feeAmount": "5.00",
    "attempt": {},
}


def test_direct_payment_posts_a_normalized_body_with_an_idempotency_key(client_factory):
    epay, calls = client_factory([{"json": DIRECT}])

    charge = epay.payments.direct_payment(
        amount=250,
        currency_code="etb",
        customer_phone="0911 234 567",
        psp_code=" TELEBIRR ",
        flow_code="USSD",
        merchant_reference="order_456",
        idempotency_key="order_456",
    )

    assert charge == DIRECT
    assert calls.calls[0].method == "POST"
    assert str(calls.url()) == "https://api.epayethiopia.com/v1/transactions/direct"
    assert calls.header("x-idempotency-key") == "order_456"
    assert calls.body() == {
        "amount": "250.00",
        "currencyCode": "ETB",
        "customerPhone": "+251911234567",
        "pspCode": "TELEBIRR",
        "flowCode": "USSD",
        "merchantReference": "order_456",
    }


def test_direct_payment_omits_unset_fields_and_generates_a_key(client_factory):
    epay, calls = client_factory([{"json": DIRECT}])

    epay.payments.direct_payment(
        amount="10", currency_code="ETB", customer_phone="0911234567", psp_code="AWASH"
    )

    assert list(calls.body()) == ["amount", "currencyCode", "customerPhone", "pspCode"]
    assert calls.header("x-idempotency-key")


@pytest.mark.parametrize("psp_code", ["", "   "])
def test_direct_payment_requires_a_provider(client_factory, psp_code):
    epay, calls = client_factory([])

    with pytest.raises(EpayValidationError, match="psp_code"):
        epay.payments.direct_payment(
            amount="10", currency_code="ETB", customer_phone="0911234567", psp_code=psp_code
        )
    assert len(calls) == 0


def test_direct_payment_retries_with_the_same_key(client_factory):
    epay, calls = client_factory([{"status": 503, "json": {}}, {"json": DIRECT}], max_retries=1)

    epay.payments.direct_payment(
        amount="10", currency_code="ETB", customer_phone="0911234567", psp_code="TELEBIRR"
    )

    assert len(calls) == 2
    assert calls.header("x-idempotency-key", 0) == calls.header("x-idempotency-key", 1)


SMS_LINK = {
    "message": "Checkout link sent via SMS",
    "checkoutUrl": "https://api.epayethiopia.com/v1/sms/p/ps_live_abc123?sig=x",
    "customerPhone": "+251911234567",
    "amount": "500.00",
    "currencyCode": "ETB",
}


def test_send_sms_link_posts_a_normalized_body(client_factory):
    epay, calls = client_factory([{"json": SMS_LINK}])

    link = epay.payments.send_sms_link(customer_phone="0911234567", currency_code="etb", amount=500)

    assert link == SMS_LINK
    assert str(calls.url()) == "https://api.epayethiopia.com/v1/transactions/sms-link"
    assert calls.body() == {
        "customerPhone": "+251911234567",
        "currencyCode": "ETB",
        "amount": "500.00",
    }


def test_send_sms_link_leaves_the_amount_to_the_customer(client_factory):
    epay, calls = client_factory([{"json": {**SMS_LINK, "amount": None}}])

    link = epay.payments.send_sms_link(customer_phone="0911234567", currency_code="ETB")

    assert link["amount"] is None
    assert "amount" not in calls.body()


def test_send_sms_link_is_never_retried(client_factory):
    epay, calls = client_factory([{"status": 503, "json": {}}], max_retries=2)

    with pytest.raises(EpayServerError):
        epay.payments.send_sms_link(customer_phone="0911234567", currency_code="ETB")
    assert len(calls) == 1


def test_receipt_returns_any_terminal_transaction(client_factory):
    failed = {
        "reference": "A3BX72KP",
        "merchantReference": "order_456",
        "status": "failed",
        "amount": "250.00",
        "chargeAmount": "250.00",
        "feeAmount": None,
        "currencyCode": "ETB",
        "paymentMethod": "TELEBIRR",
        "customer": {"name": None, "email": None, "phone": "+251911234567"},
        "paidAt": None,
        "createdAt": "2026-10-12T09:10:00.000Z",
    }
    epay, calls = client_factory([{"json": failed}])

    receipt = epay.payments.receipt("A3BX72KP")

    assert str(calls.url()).endswith("/transactions/A3BX72KP/receipt")
    assert receipt["status"] == "failed"
    assert receipt["paidAt"] is None


def test_receipt_reports_a_pending_transaction_as_a_bad_request(client_factory):
    epay, _ = client_factory(
        [{"status": 400, "json": {"status": "error", "data": {"message": "pending"}}}]
    )

    with pytest.raises(EpayBadRequestError):
        epay.payments.receipt("A3BX72KP")


# --- transport behaviour ----------------------------------------------------


def test_a_429_is_retried_and_reuses_the_idempotency_key(client_factory):
    epay, calls = client_factory(
        [
            {
                "status": 429,
                "json": {"status": "error", "data": {"message": "Rate limit exceeded"}},
                "headers": {"retry-after": "0"},
            },
            {"json": SESSION},
        ],
        max_retries=2,
    )

    session = epay.payments.initialize(
        amount="10.00", currency_code="ETB", customer_phone="0911234567", idempotency_key="order_9"
    )

    assert session == SESSION
    assert len(calls) == 2
    assert calls.header("x-idempotency-key", 0) == "order_9"
    assert calls.header("x-idempotency-key", 1) == "order_9", (
        "the retry must carry the same key or it would double-charge"
    )


def test_a_5xx_on_a_get_is_retried(client_factory):
    epay, calls = client_factory([{"status": 503}, {"json": {"reference": "P1"}}], max_retries=1)

    assert epay.transactions.retrieve("P1")["reference"] == "P1"
    assert len(calls) == 2


def test_a_4xx_is_not_retried(client_factory):
    epay, calls = client_factory(
        [{"status": 401, "json": {"status": "error", "data": {"message": "Invalid API key"}}}],
        max_retries=3,
    )

    with pytest.raises(EpayAuthenticationError):
        epay.transactions.retrieve("P1")

    assert len(calls) == 1


def test_the_rate_limit_error_surfaces_once_the_budget_runs_out(client_factory):
    epay, calls = client_factory(
        [
            {"status": 429, "headers": {"retry-after": "0"}},
            {"status": 429, "headers": {"retry-after": "0"}},
        ],
        max_retries=1,
    )

    with pytest.raises(EpayRateLimitError) as caught:
        epay.transactions.retrieve("P1")

    assert caught.value.retry_after_seconds == 0.0
    assert len(calls) == 2


def test_a_transport_error_is_retried_then_surfaced():
    attempts = {"count": 0}

    def handler(request):
        attempts["count"] += 1
        raise httpx.ConnectError("connection refused", request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    with Epay("sk_test_abc", http_client=http_client, max_retries=1) as epay:
        with pytest.raises(EpayConnectionError, match="Could not reach the ePay API"):
            epay.transactions.retrieve("P1")

    assert attempts["count"] == 2


def test_a_timeout_maps_to_the_timeout_error():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    with Epay("sk_test_abc", http_client=http_client, max_retries=0) as epay:
        with pytest.raises(EpayTimeoutError, match="timed out"):
            epay.transactions.retrieve("P1")


def test_default_headers_are_merged_into_every_request(client_factory):
    epay, calls = client_factory([{"json": {}}], default_headers={"X-Trace-Id": "trace_1"})
    epay.transactions.retrieve("P1")
    assert calls.header("x-trace-id") == "trace_1"


def test_the_escape_hatch_reaches_unmodelled_endpoints(client_factory):
    epay, calls = client_factory([{"json": {"ok": True}}])

    data = epay.request("GET", "/some/future/endpoint", params={"limit": 10})

    assert data == {"ok": True}
    assert str(calls.url()) == "https://api.epayethiopia.com/v1/some/future/endpoint?limit=10"


def test_a_supplied_http_client_is_not_closed_by_the_sdk():
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    epay = Epay("sk_test_abc", http_client=http_client)
    epay.close()
    assert not http_client.is_closed, "the SDK must not close a pool it did not create"
    http_client.close()
