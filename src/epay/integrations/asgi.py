"""Webhook verification for FastAPI, Starlette, and Litestar.

::

    from fastapi import FastAPI, HTTPException, Request
    from epay import EpayWebhookSignatureError
    from epay.integrations.asgi import construct_event_from_request

    app = FastAPI()

    @app.post("/webhooks/epay", status_code=200)
    async def epay_webhook(request: Request):
        try:
            event = await construct_event_from_request(request, settings.epay_webhook_secret)
        except EpayWebhookSignatureError as error:
            raise HTTPException(status_code=401, detail=str(error))

        await queue.enqueue(event)  # acknowledge fast, process later
        return {"received": True}

Take the whole ``Request``, not a parsed Pydantic model: FastAPI would hand you
re-serialized JSON, whose digest no longer matches.

For reuse across routes, :class:`EpayWebhookVerifier` is callable and works as a
dependency::

    verifier = EpayWebhookVerifier(settings.epay_webhook_secret)

    @app.post("/webhooks/epay")
    async def epay_webhook(request: Request):
        event = await verifier(request)
"""

from __future__ import annotations

from typing import Any

from .._types import WebhookEvent
from ..webhooks import SIGNATURE_HEADER, construct_webhook_event

__all__ = ["construct_event_from_request", "EpayWebhookVerifier"]


async def construct_event_from_request(request: Any, secret: str) -> WebhookEvent:
    """Verifies an ASGI request and returns the parsed event.

    Awaits ``request.body()`` to get the exact bytes that were signed.

    Raises:
        EpayWebhookSignatureError: if the header is missing or does not match.
        EpayValidationError: if the verified body is not a JSON object.
    """
    raw_body = await request.body()
    signature = request.headers.get(SIGNATURE_HEADER)
    return construct_webhook_event(raw_body, signature, secret)


class EpayWebhookVerifier:
    """A reusable, callable verifier bound to one secret."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    async def __call__(self, request: Any) -> WebhookEvent:
        """Verifies the request and returns the parsed event."""
        return await construct_event_from_request(request, self._secret)
