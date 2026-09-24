"""Synchronous ePay client."""

from __future__ import annotations

from datetime import date, datetime
from types import TracebackType
from typing import Any, Dict, List, Optional, Type, Union, cast

import httpx

from . import _specs
from ._config import Config, resolve_config
from ._transport import RequestSpec, SyncTransport
from ._types import (
    EpayMode,
    InitializedPayment,
    PaymentProvider,
    PaymentProviderItem,
    Transaction,
    TransactionTimeline,
    VerifiedPayment,
)
from .helpers import AmountInput, mask_secret
from .pagination import TransactionPage
from .webhooks import Webhooks

__all__ = ["Epay"]


class Payments:
    """Operations on the payment lifecycle."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def initialize(
        self,
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
    ) -> InitializedPayment:
        """Creates a payment session and returns a hosted checkout URL.

        ``amount``, ``currency_code``, and ``customer_phone`` are normalized
        before the request is sent: amounts are formatted to two decimal places,
        currencies uppercased, and phone numbers rewritten to ``+251XXXXXXXXX``.

        Redirect the customer to ``checkoutUrl`` and store ``reference`` to
        reconcile the payment later.

        Args:
            idempotency_key: Up to 255 characters. Resending the same key within
                the session window returns the original response instead of
                creating a second transaction. When omitted the SDK generates a
                fresh key per call, which makes its internal retries safe but
                does not deduplicate across separate calls -- pass your order id
                to get that guarantee.

        Raises:
            EpayValidationError: if a field fails local validation.
            EpayBadRequestError: ``400`` -- amount or currency rejected.
            EpayNotFoundError: ``404`` -- no active payment source on the account.
            EpayRateLimitError: ``429`` -- rate limit exhausted after retries.
        """
        return cast(
            InitializedPayment,
            self._transport.request(
                _specs.initialize_spec(
                    amount=amount,
                    currency_code=currency_code,
                    customer_phone=customer_phone,
                    merchant_reference=merchant_reference,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    return_url=return_url,
                    callback_url=callback_url,
                    idempotency_key=idempotency_key,
                )
            ),
        )

    def verify(self, reference: str) -> VerifiedPayment:
        """Returns the full receipt for a completed transaction.

        Call this before fulfilling an order. The API rejects any transaction
        that is not yet ``completed``, so use
        :meth:`Transactions.retrieve` first if you would rather branch on status
        than catch an error.

        Raises:
            EpayBadRequestError: ``400`` -- the transaction is not yet completed.
            EpayNotFoundError: ``404`` -- no such transaction on your account.
        """
        return cast(VerifiedPayment, self._transport.request(_specs.verify_spec(reference)))

    def cancel(self, reference: str) -> None:
        """Cancels a ``pending`` or ``processing`` transaction.

        Fires a ``payment.cancelled`` webhook. Cancellation is irreversible: the
        checkout session is invalidated and the customer can no longer pay.

        Raises:
            EpayBadRequestError: ``400`` -- the transaction is not cancellable.
            EpayNotFoundError: ``404`` -- no such transaction on your account.
        """
        self._transport.request(_specs.cancel_spec(reference))


class Transactions:
    """Read operations over transaction history."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def list(
        self,
        *,
        from_date: Optional[Union[str, date, datetime]] = None,
        to_date: Optional[Union[str, date, datetime]] = None,
        currency: Optional[str] = None,
        status: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> TransactionPage:
        """Returns a page of transactions, newest first, 10 per page.

        Filters persist across pages. When both dates are given the API rejects
        ranges longer than 90 days.

        Iterate the returned page to walk every following page lazily.

        Raises:
            EpayValidationError: if the range is inverted or a filter is malformed.
            EpayBadRequestError: ``400`` -- range too long, or unknown status/currency.
        """
        response = self._transport.request(
            _specs.list_transactions_spec(
                from_date=from_date,
                to_date=to_date,
                currency=currency,
                status=status,
                cursor=cursor,
            )
        )

        def fetch_next(next_cursor: str) -> TransactionPage:
            return self.list(
                from_date=from_date,
                to_date=to_date,
                currency=currency,
                status=status,
                cursor=next_cursor,
            )

        return TransactionPage(response, fetch_next)

    def retrieve(self, reference: str) -> Transaction:
        """Returns the current state of a single transaction.

        Raises:
            EpayNotFoundError: ``404`` -- no such transaction on your account.
        """
        return cast(Transaction, self._transport.request(_specs.retrieve_spec(reference)))

    def timeline(self, reference: str) -> TransactionTimeline:
        """Returns every event recorded against a transaction, earliest first.

        ``events`` is empty until the first provider event arrives.

        Raises:
            EpayNotFoundError: ``404`` -- no such transaction on your account.
        """
        return cast(TransactionTimeline, self._transport.request(_specs.timeline_spec(reference)))


class PaymentProviders:
    """Read operations over the account's payment providers.

    Both endpoints are mode-aware: a ``sk_test_...`` key returns sandbox
    providers and a ``sk_live_...`` key returns live ones.
    """

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def list(self) -> List[PaymentProviderItem]:
        """Returns a compact provider list suited to dropdowns.

        Requires the ``list_platform_payment_provider`` permission.

        Raises:
            EpayPermissionDeniedError: ``403`` -- the key lacks that permission.
        """
        response = self._transport.request(_specs.providers_list_spec()) or {}
        return response.get("data") or []

    def get_all(self) -> List[PaymentProvider]:
        """Returns every provider with its category and enabled state.

        Disabled providers are included so your UI can show them as unavailable
        rather than having them silently disappear.

        Requires the ``get_platform_payment_provider`` permission.

        Raises:
            EpayPermissionDeniedError: ``403`` -- the key lacks that permission.
        """
        response = self._transport.request(_specs.providers_get_all_spec()) or {}
        return response.get("data") or []

    def list_enabled(self) -> List[PaymentProvider]:
        """Returns only the providers the account can currently route through."""
        return [provider for provider in self.get_all() if provider.get("isEnabled")]


class Epay:
    """Synchronous client for the ePay Business API.

    The key prefix selects the environment -- ``sk_test_...`` hits the sandbox,
    ``sk_live_...`` moves real money -- so there is no separate mode to set::

        from epay import Epay

        epay = Epay()  # reads EPAY_SECRET_KEY

        session = epay.payments.initialize(
            amount="250.00",
            currency_code="ETB",
            customer_phone="+251911234567",
            merchant_reference="order_123",
        )

        redirect(session["checkoutUrl"])

    Use it as a context manager, or call :meth:`close`, to release the
    connection pool::

        with Epay() as epay:
            epay.payments.verify(reference)

    Failed requests raise an :class:`~epay.errors.EpayAPIError` subclass.
    Transient failures -- ``429``, ``5xx``, and network errors -- are retried
    with exponential backoff before surfacing.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        webhook_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        default_headers: Optional[Dict[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        """
        Args:
            api_key: Secret key. Falls back to ``EPAY_SECRET_KEY``.
            webhook_secret: Webhook signing secret. Falls back to
                ``EPAY_WEBHOOK_SECRET``.
            base_url: API root. Falls back to ``EPAY_BASE_URL``, then the
                production root.
            timeout: Per-attempt timeout in seconds. Defaults to 30.
            max_retries: Retries after the first attempt. Defaults to 2.
            default_headers: Headers merged into every request.
            http_client: An existing ``httpx.Client`` to reuse, for connection
                pooling, proxies, or mTLS. The SDK will not close a client it
                did not create.

        Raises:
            EpayConfigError: if no API key is available, the key is not a secret
                key, or an option is out of range.
        """
        self._config: Config = resolve_config(
            api_key,
            webhook_secret=webhook_secret,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=default_headers,
        )
        self._transport = SyncTransport(self._config, http_client)

        #: Initialize, verify, and cancel payment sessions.
        self.payments = Payments(self._transport)
        #: List, retrieve, and inspect the timeline of transactions.
        self.transactions = Transactions(self._transport)
        #: Discover which providers and flows the account can use.
        self.payment_providers = PaymentProviders(self._transport)
        #: Verify webhook signatures and parse events.
        self.webhooks = Webhooks(self._config.webhook_secret)

    @property
    def mode(self) -> Optional[EpayMode]:
        """Which environment the configured key targets, or ``None`` if unrecognised."""
        return self._config.mode

    @property
    def is_sandbox(self) -> bool:
        """Whether the configured key targets the sandbox."""
        return self._config.mode == "sandbox"

    @property
    def base_url(self) -> str:
        """The API root every request is sent to."""
        return self._config.base_url

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        retryable: Optional[bool] = None,
    ) -> Any:
        """Escape hatch for endpoints this SDK version does not model yet.

        Applies the same authentication, timeout, retry, and error handling as
        the typed methods.
        """
        return self._transport.request(
            RequestSpec(
                method=method.upper(),
                path=path,
                params=params,
                json=json,
                headers=dict(headers or {}),
                retryable=retryable,
            )
        )

    def close(self) -> None:
        """Closes the underlying connection pool, if this client created it."""
        self._transport.close()

    def __enter__(self) -> Epay:
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        """Renders the client without leaking the API key."""
        return "Epay(mode={}, api_key={})".format(
            self._config.mode or "unknown", mask_secret(self._config.api_key)
        )
