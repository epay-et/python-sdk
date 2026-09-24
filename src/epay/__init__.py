"""ePay Business API client for Python.

Accept payments from every major Ethiopian mobile wallet and bank with one
integration::

    from epay import Epay

    epay = Epay()  # reads EPAY_SECRET_KEY

    session = epay.payments.initialize(
        amount="250.00",
        currency_code="ETB",
        customer_phone="+251911234567",
        merchant_reference="order_123",
    )

    redirect(session["checkoutUrl"])

An async client is available as :class:`AsyncEpay`, and framework webhook
helpers live in :mod:`epay.integrations`.
"""

from __future__ import annotations

from ._config import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    mode_from_api_key,
)
from ._types import (
    CANCELLABLE_STATUSES,
    TRANSACTION_STATUSES,
    WEBHOOK_EVENT_TYPES,
    EpayMode,
    InitializedPayment,
    PaymentProvider,
    PaymentProviderItem,
    TimelineEvent,
    Transaction,
    TransactionCustomer,
    TransactionListResponse,
    TransactionStatus,
    TransactionTimeline,
    VerifiedPayment,
    WebhookEvent,
    WebhookEventType,
)
from ._version import __version__
from .async_client import AsyncEpay
from .client import Epay
from .errors import (
    EpayAPIError,
    EpayAuthenticationError,
    EpayBadRequestError,
    EpayConfigError,
    EpayConflictError,
    EpayConnectionError,
    EpayError,
    EpayNotFoundError,
    EpayPermissionDeniedError,
    EpayRateLimitError,
    EpayServerError,
    EpayTimeoutError,
    EpayUnprocessableEntityError,
    EpayValidationError,
    EpayWebhookSignatureError,
)
from .helpers import (
    MAX_AMOUNT,
    MAX_LIST_RANGE_DAYS,
    format_amount,
    normalize_currency,
    normalize_phone,
)
from .pagination import PAGE_SIZE, AsyncTransactionPage, TransactionPage
from .webhooks import (
    SIGNATURE_HEADER,
    Webhooks,
    construct_webhook_event,
    is_known_webhook_event,
    sign_webhook_payload,
    verify_webhook_signature,
)

__all__ = [
    "__version__",
    # Clients
    "Epay",
    "AsyncEpay",
    # Configuration
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT",
    "mode_from_api_key",
    # Errors
    "EpayError",
    "EpayAPIError",
    "EpayAuthenticationError",
    "EpayBadRequestError",
    "EpayConfigError",
    "EpayConflictError",
    "EpayConnectionError",
    "EpayNotFoundError",
    "EpayPermissionDeniedError",
    "EpayRateLimitError",
    "EpayServerError",
    "EpayTimeoutError",
    "EpayUnprocessableEntityError",
    "EpayValidationError",
    "EpayWebhookSignatureError",
    # Helpers
    "MAX_AMOUNT",
    "MAX_LIST_RANGE_DAYS",
    "format_amount",
    "normalize_currency",
    "normalize_phone",
    # Pagination
    "PAGE_SIZE",
    "TransactionPage",
    "AsyncTransactionPage",
    # Webhooks
    "SIGNATURE_HEADER",
    "Webhooks",
    "construct_webhook_event",
    "is_known_webhook_event",
    "sign_webhook_payload",
    "verify_webhook_signature",
    # Types
    "CANCELLABLE_STATUSES",
    "TRANSACTION_STATUSES",
    "WEBHOOK_EVENT_TYPES",
    "EpayMode",
    "InitializedPayment",
    "PaymentProvider",
    "PaymentProviderItem",
    "TimelineEvent",
    "Transaction",
    "TransactionCustomer",
    "TransactionListResponse",
    "TransactionStatus",
    "TransactionTimeline",
    "VerifiedPayment",
    "WebhookEvent",
    "WebhookEventType",
]
