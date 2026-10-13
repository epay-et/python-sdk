"""Request builders shared by the sync and async clients.

Each function validates its inputs and returns a :class:`RequestSpec`. Keeping
validation here means the sync and async surfaces enforce identical rules.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union, cast

from ._transport import RequestSpec
from ._types import TRANSACTION_STATUSES, PaymentProvider
from .errors import EpayValidationError
from .helpers import (
    AmountInput,
    format_amount,
    format_date_param,
    normalize_currency,
    normalize_phone,
    require_reference,
)

__all__ = [
    "initialize_spec",
    "direct_payment_spec",
    "sms_link_spec",
    "receipt_spec",
    "verify_spec",
    "cancel_spec",
    "list_transactions_spec",
    "retrieve_spec",
    "timeline_spec",
    "providers_list_spec",
    "providers_get_all_spec",
]

_OPTIONAL_INITIALIZE_FIELDS = (
    "merchantReference",
    "email",
    "firstName",
    "lastName",
    "returnUrl",
    "callbackUrl",
)


def initialize_spec(
    *,
    amount: AmountInput,
    currency_code: str,
    customer_phone: str,
    merchant_reference: Optional[str] = None,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    return_url: Optional[str] = None,
    callback_url: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> RequestSpec:
    """Builds the ``POST /transactions/initialize`` request.

    When ``idempotency_key`` is omitted a fresh one is generated per call, which
    makes the SDK's internal retries safe but does not deduplicate across
    separate calls.
    """
    key = _resolve_idempotency_key(idempotency_key)

    body: Dict[str, Any] = {
        "amount": format_amount(amount),
        "currencyCode": normalize_currency(currency_code),
        "customerPhone": normalize_phone(customer_phone),
    }

    # Only forward optional fields the caller actually set, so the API applies
    # its own defaults rather than receiving explicit nulls.
    optional = {
        "merchantReference": merchant_reference,
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "returnUrl": return_url,
        "callbackUrl": callback_url,
    }
    for field_name in _OPTIONAL_INITIALIZE_FIELDS:
        value = optional[field_name]
        if value is not None:
            body[field_name] = value

    return RequestSpec(
        method="POST",
        path="/transactions/initialize",
        json=body,
        headers={"x-idempotency-key": key},
        # Safe to retry: every attempt carries the same idempotency key.
        retryable=True,
    )


def direct_payment_spec(
    *,
    amount: AmountInput,
    currency_code: str,
    customer_phone: str,
    psp_code: str,
    flow_code: Optional[str] = None,
    merchant_reference: Optional[str] = None,
    callback_url: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> RequestSpec:
    """Builds the ``POST /transactions/direct`` request."""
    key = _resolve_idempotency_key(idempotency_key)

    body: Dict[str, Any] = {
        "amount": format_amount(amount),
        "currencyCode": normalize_currency(currency_code),
        "customerPhone": normalize_phone(customer_phone),
        "pspCode": _require_code(psp_code, "psp_code"),
    }
    if flow_code is not None:
        body["flowCode"] = _require_code(flow_code, "flow_code")
    if merchant_reference is not None:
        body["merchantReference"] = merchant_reference
    if callback_url is not None:
        body["callbackUrl"] = callback_url

    return RequestSpec(
        method="POST",
        path="/transactions/direct",
        json=body,
        headers={"x-idempotency-key": key},
        # Safe to retry: every attempt carries the same idempotency key.
        retryable=True,
    )


def sms_link_spec(
    *,
    customer_phone: str,
    currency_code: str,
    amount: Optional[AmountInput] = None,
) -> RequestSpec:
    """Builds the ``POST /transactions/sms-link`` request."""
    body: Dict[str, Any] = {
        "customerPhone": normalize_phone(customer_phone),
        "currencyCode": normalize_currency(currency_code),
    }
    if amount is not None:
        body["amount"] = format_amount(amount)

    return RequestSpec(
        method="POST",
        path="/transactions/sms-link",
        json=body,
        # The endpoint takes no idempotency key, so a retry after a lost
        # response would text the customer a second time.
        retryable=False,
    )


def receipt_spec(reference: str) -> RequestSpec:
    """Builds the ``GET /transactions/:reference/receipt`` request."""
    from urllib.parse import quote

    return RequestSpec(
        method="GET",
        path="/transactions/{}/receipt".format(quote(require_reference(reference), safe="")),
    )


def verify_spec(reference: str) -> RequestSpec:
    """Builds the ``GET /transactions/:reference/verify`` request."""
    from urllib.parse import quote

    return RequestSpec(
        method="GET",
        path="/transactions/{}/verify".format(quote(require_reference(reference), safe="")),
    )


def cancel_spec(reference: str) -> RequestSpec:
    """Builds the ``POST /transactions/:reference/cancel`` request."""
    from urllib.parse import quote

    return RequestSpec(
        method="POST",
        path="/transactions/{}/cancel".format(quote(require_reference(reference), safe="")),
        # Cancelling twice is rejected with 400 rather than duplicated, but the
        # endpoint takes no idempotency key, so a retried attempt could act on a
        # request the server already processed.
        retryable=False,
    )


def retrieve_spec(reference: str) -> RequestSpec:
    """Builds the ``GET /transactions/:reference`` request."""
    from urllib.parse import quote

    return RequestSpec(
        method="GET",
        path="/transactions/{}".format(quote(require_reference(reference), safe="")),
    )


def timeline_spec(reference: str) -> RequestSpec:
    """Builds the ``GET /transactions/:reference/timeline`` request."""
    from urllib.parse import quote

    return RequestSpec(
        method="GET",
        path="/transactions/{}/timeline".format(quote(require_reference(reference), safe="")),
    )


def list_transactions_spec(
    *,
    from_date: Optional[Union[str, date, datetime]] = None,
    to_date: Optional[Union[str, date, datetime]] = None,
    currency: Optional[str] = None,
    status: Optional[str] = None,
    cursor: Optional[str] = None,
) -> RequestSpec:
    """Builds the ``GET /transactions`` request.

    Raises:
        EpayValidationError: if the range is inverted or the status is unknown.
    """
    params: Dict[str, Any] = {}

    if from_date is not None:
        params["from"] = format_date_param(from_date, "from_date")
    if to_date is not None:
        params["to"] = format_date_param(to_date, "to_date")
    if "from" in params and "to" in params and params["from"] > params["to"]:
        raise EpayValidationError(
            "from_date ({}) must not be later than to_date ({})".format(
                params["from"], params["to"]
            )
        )

    if currency is not None:
        params["currency"] = normalize_currency(currency, "currency")

    if status is not None:
        if status not in TRANSACTION_STATUSES:
            raise EpayValidationError(
                "status must be one of {}, received {!r}".format(
                    ", ".join(TRANSACTION_STATUSES), status
                )
            )
        params["status"] = status

    if cursor is not None:
        params["cursor"] = cursor

    return RequestSpec(method="GET", path="/transactions", params=params)


def providers_list_spec() -> RequestSpec:
    """Builds the ``GET /payment-providers/list`` request."""
    return RequestSpec(method="GET", path="/payment-providers/list")


def providers_get_all_spec() -> RequestSpec:
    """Builds the ``GET /payment-providers`` request."""
    return RequestSpec(method="GET", path="/payment-providers")


def direct_payment_providers(providers: List[PaymentProvider]) -> List[PaymentProvider]:
    """Keeps only direct-payment flows, and the providers that have one."""
    result: List[PaymentProvider] = []
    for provider in providers:
        flows = [flow for flow in provider.get("flows") or [] if flow.get("supportsDirectPayment")]
        if flows:
            result.append(cast(PaymentProvider, {**provider, "flows": flows}))
    return result


def _resolve_idempotency_key(idempotency_key: Optional[str]) -> str:
    """Uses the caller's key, or generates one for this call."""
    key = idempotency_key or f"epay_{uuid.uuid4()}"
    if len(key) > 255:
        raise EpayValidationError(
            f"idempotency_key must be at most 255 characters, received {len(key)}"
        )
    return key


def _require_code(value: str, field: str) -> str:
    """Validates a provider or flow code is present, and trims it."""
    code = value.strip() if isinstance(value, str) else ""
    if not code:
        raise EpayValidationError(f"{field} must be a non-empty string")
    return code
