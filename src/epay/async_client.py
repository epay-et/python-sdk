"""Asynchronous ePay client.

Mirrors :mod:`epay.client` method for method; only the awaiting differs. See the
sync docstrings for the full argument and error detail.
"""

from __future__ import annotations

from datetime import date, datetime
from types import TracebackType
from typing import Any, Dict, List, Optional, Type, Union, cast

import httpx

from . import _specs
from ._config import Config, resolve_config
from ._transport import AsyncTransport, RequestSpec
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
from .pagination import AsyncTransactionPage
from .webhooks import Webhooks

__all__ = ["AsyncEpay"]


class AsyncPayments:
    """Operations on the payment lifecycle. See :class:`epay.client.Payments`."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def initialize(
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

        When ``idempotency_key`` is omitted the SDK generates a fresh one per
        call, which makes its internal retries safe but does not deduplicate
        across separate calls.
        """
        return cast(
            InitializedPayment,
            await self._transport.request(
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

    async def verify(self, reference: str) -> VerifiedPayment:
        """Returns the full receipt for a completed transaction.

        Raises ``EpayBadRequestError`` if the transaction is not yet completed.
        """
        return cast(VerifiedPayment, await self._transport.request(_specs.verify_spec(reference)))

    async def cancel(self, reference: str) -> None:
        """Cancels a ``pending`` or ``processing`` transaction. Irreversible."""
        await self._transport.request(_specs.cancel_spec(reference))


class AsyncTransactions:
    """Read operations over transaction history."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def list(
        self,
        *,
        from_date: Optional[Union[str, date, datetime]] = None,
        to_date: Optional[Union[str, date, datetime]] = None,
        currency: Optional[str] = None,
        status: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> AsyncTransactionPage:
        """Returns a page of transactions, newest first, 10 per page.

        ``async for`` over the returned page to walk every following page.
        """
        response = await self._transport.request(
            _specs.list_transactions_spec(
                from_date=from_date,
                to_date=to_date,
                currency=currency,
                status=status,
                cursor=cursor,
            )
        )

        async def fetch_next(next_cursor: str) -> AsyncTransactionPage:
            return await self.list(
                from_date=from_date,
                to_date=to_date,
                currency=currency,
                status=status,
                cursor=next_cursor,
            )

        return AsyncTransactionPage(response, fetch_next)

    async def retrieve(self, reference: str) -> Transaction:
        """Returns the current state of a single transaction."""
        return cast(Transaction, await self._transport.request(_specs.retrieve_spec(reference)))

    async def timeline(self, reference: str) -> TransactionTimeline:
        """Returns every event recorded against a transaction, earliest first."""
        return cast(
            TransactionTimeline, await self._transport.request(_specs.timeline_spec(reference))
        )


class AsyncPaymentProviders:
    """Read operations over the account's payment providers."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def list(self) -> List[PaymentProviderItem]:
        """Compact provider list. Needs ``list_platform_payment_provider``."""
        response = await self._transport.request(_specs.providers_list_spec()) or {}
        return response.get("data") or []

    async def get_all(self) -> List[PaymentProvider]:
        """Full provider list. Needs ``get_platform_payment_provider``."""
        response = await self._transport.request(_specs.providers_get_all_spec()) or {}
        return response.get("data") or []

    async def list_enabled(self) -> List[PaymentProvider]:
        """Only the providers the account can currently route through."""
        return [provider for provider in await self.get_all() if provider.get("isEnabled")]


class AsyncEpay:
    """Asynchronous client for the ePay Business API.

    ::

        from epay import AsyncEpay

        async with AsyncEpay() as epay:
            session = await epay.payments.initialize(
                amount="250.00",
                currency_code="ETB",
                customer_phone="+251911234567",
            )

            async for transaction in await epay.transactions.list(status="completed"):
                print(transaction["reference"])

    Always close the client -- via ``async with`` or :meth:`aclose` -- or the
    connection pool leaks.
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
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        """See :class:`epay.client.Epay` for the argument reference.

        Args:
            http_client: An existing ``httpx.AsyncClient`` to reuse. The SDK
                will not close a client it did not create.
        """
        self._config: Config = resolve_config(
            api_key,
            webhook_secret=webhook_secret,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=default_headers,
        )
        self._transport = AsyncTransport(self._config, http_client)

        #: Initialize, verify, and cancel payment sessions.
        self.payments = AsyncPayments(self._transport)
        #: List, retrieve, and inspect the timeline of transactions.
        self.transactions = AsyncTransactions(self._transport)
        #: Discover which providers and flows the account can use.
        self.payment_providers = AsyncPaymentProviders(self._transport)
        #: Verify webhook signatures and parse events. Synchronous: HMAC is cheap.
        self.webhooks = Webhooks(self._config.webhook_secret)

    @property
    def mode(self) -> Optional[EpayMode]:
        """Which environment the configured key targets."""
        return self._config.mode

    @property
    def is_sandbox(self) -> bool:
        """Whether the configured key targets the sandbox."""
        return self._config.mode == "sandbox"

    @property
    def base_url(self) -> str:
        """The API root every request is sent to."""
        return self._config.base_url

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        retryable: Optional[bool] = None,
    ) -> Any:
        """Escape hatch for endpoints this SDK version does not model yet."""
        return await self._transport.request(
            RequestSpec(
                method=method.upper(),
                path=path,
                params=params,
                json=json,
                headers=dict(headers or {}),
                retryable=retryable,
            )
        )

    async def aclose(self) -> None:
        """Closes the underlying connection pool, if this client created it."""
        await self._transport.aclose()

    async def __aenter__(self) -> AsyncEpay:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        """Renders the client without leaking the API key."""
        return "AsyncEpay(mode={}, api_key={})".format(
            self._config.mode or "unknown", mask_secret(self._config.api_key)
        )
