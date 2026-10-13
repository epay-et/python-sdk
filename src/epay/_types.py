"""Wire types for the ePay Business API.

Named with a leading underscore so it can never shadow the stdlib ``types``
module; every name here is re-exported from the ``epay`` package root.

Responses are returned as ``TypedDict`` instances, which are plain ``dict`` at
runtime. That keeps the SDK dependency-light and means a field the API adds
later is still readable via ``response["newField"]`` without an SDK upgrade.
"""

from __future__ import annotations

# Literal and TypedDict are stdlib from 3.8, and this package requires 3.9+.
from typing import Any, Dict, List, Literal, Optional, TypedDict

__all__ = [
    "EpayMode",
    "TransactionStatus",
    "WebhookEventType",
    "TRANSACTION_STATUSES",
    "CANCELLABLE_STATUSES",
    "WEBHOOK_EVENT_TYPES",
    "InitializedPayment",
    "DirectPayment",
    "SmsLink",
    "Receipt",
    "Transaction",
    "TransactionCustomer",
    "VerifiedPayment",
    "TransactionListResponse",
    "TimelineEvent",
    "TransactionTimeline",
    "PaymentProviderItem",
    "PaymentProviderFlow",
    "PaymentProvider",
    "WebhookEvent",
]

#: Whether a key or event belongs to live traffic or the sandbox.
EpayMode = Literal["live", "sandbox"]

#: Lifecycle states a transaction can be in.
TransactionStatus = Literal[
    "pending",
    "processing",
    "completed",
    "failed",
    "cancelled",
    "reversed",
    "refunding",
    "refunded",
]

#: Webhook event names.
WebhookEventType = Literal[
    "payment.success",
    "payment.failed",
    "payment.cancelled",
    "payment.refunding",
    "payment.refunded",
    "payment.reversed",
]

#: Every status value the API recognises, for runtime validation.
TRANSACTION_STATUSES = (
    "pending",
    "processing",
    "completed",
    "failed",
    "cancelled",
    "reversed",
    "refunding",
    "refunded",
)

#: Statuses that can still be cancelled via the API.
CANCELLABLE_STATUSES = ("pending", "processing")

#: Every webhook event name, for runtime validation.
WEBHOOK_EVENT_TYPES = (
    "payment.success",
    "payment.failed",
    "payment.cancelled",
    "payment.refunding",
    "payment.refunded",
    "payment.reversed",
)


class InitializedPayment(TypedDict):
    """Response of ``POST /v1/transactions/initialize``."""

    reference: str
    checkoutUrl: str
    status: str
    expiresAt: str


class DirectPayment(TypedDict):
    """Response of ``POST /v1/transactions/direct``.

    ``status`` is always ``pending``: the outcome arrives by webhook once the
    customer authorizes on their phone. ``attempt`` holds provider-specific
    session data whose shape varies by provider.
    """

    reference: str
    status: TransactionStatus
    chargeAmount: str
    feeAmount: str
    attempt: Dict[str, Any]


class SmsLink(TypedDict):
    """Response of ``POST /v1/transactions/sms-link``.

    ``amount`` is ``None`` when the customer enters it. The link is valid for
    1 hour.
    """

    message: str
    checkoutUrl: str
    customerPhone: str
    amount: Optional[str]
    currencyCode: str


class Transaction(TypedDict):
    """A transaction as returned by retrieve and list."""

    reference: str
    merchantReference: Optional[str]
    status: TransactionStatus
    amount: str
    currencyCode: str
    paidAt: Optional[str]
    createdAt: str


class TransactionCustomer(TypedDict):
    """Customer details on a verified receipt or webhook event."""

    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]


class VerifiedPayment(TypedDict):
    """Response of ``GET /v1/transactions/:reference/verify``."""

    reference: str
    merchantReference: Optional[str]
    status: TransactionStatus
    amount: str
    serviceFee: Optional[str]
    currencyCode: Optional[str]
    paymentMethod: Optional[str]
    customer: TransactionCustomer
    paidAt: str
    createdAt: str


class Receipt(TypedDict):
    """Response of ``GET /v1/transactions/:reference/receipt``.

    ``status`` is terminal: ``completed``, ``failed``, or ``cancelled``.
    ``paidAt`` is ``None`` for failed and cancelled transactions.
    """

    reference: str
    merchantReference: Optional[str]
    status: TransactionStatus
    amount: str
    chargeAmount: str
    feeAmount: Optional[str]
    currencyCode: Optional[str]
    paymentMethod: Optional[str]
    customer: TransactionCustomer
    paidAt: Optional[str]
    createdAt: str


class TransactionListResponse(TypedDict):
    """Raw body of ``GET /v1/transactions``. Page size is fixed at 10."""

    data: List[Transaction]
    nextCursor: Optional[str]
    hasMore: bool


class TimelineEvent(TypedDict):
    """A single entry in a transaction timeline."""

    eventType: str
    occurredAt: str
    errorCode: Optional[str]
    errorMessage: Optional[str]


class TransactionTimeline(TypedDict):
    """Response of ``GET /v1/transactions/:reference/timeline``."""

    reference: str
    events: List[TimelineEvent]


class PaymentProviderItem(TypedDict):
    """Compact provider entry from ``GET /v1/payment-providers/list``."""

    providerCode: str
    providerName: Optional[str]
    flowCode: str


class PaymentProviderFlow(TypedDict):
    """A payment flow a provider supports.

    Pass ``flowCode`` to a direct payment. ``isDefault`` marks the flow to
    pre-select, and ``supportsDirectPayment`` the flows a direct payment accepts.
    """

    flowCode: str
    isDefault: bool
    supportsDirectPayment: bool


class PaymentProvider(TypedDict):
    """Provider entry from ``GET /v1/payment-providers``, with its flows grouped.

    Pass ``providerCode`` as ``psp_code`` to a direct payment.
    """

    providerCode: str
    providerName: Optional[str]
    providerCategory: Optional[str]
    flows: List[PaymentProviderFlow]


class _WebhookEventExtras(TypedDict, total=False):
    """Fields present only on some events, such as direct payments."""

    customerPhone: str
    pspCode: str
    occurredAt: str
    reason: str


class WebhookEvent(_WebhookEventExtras):
    """Payload delivered to your webhook endpoint.

    Note the currency field is ``currency`` here, not ``currencyCode`` as on the
    transaction endpoints.
    """

    event: WebhookEventType
    mode: EpayMode
    reference: str
    merchantReference: Optional[str]
    amount: Optional[str]
    serviceFee: Optional[str]
    currency: Optional[str]
    status: TransactionStatus
    paymentMethod: Optional[str]
    customer: TransactionCustomer
    paidAt: Optional[str]
    createdAt: str


#: A JSON object as returned by the API.
JSONDict = Dict[str, Any]
