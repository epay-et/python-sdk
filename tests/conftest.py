"""Shared fixtures: an httpx MockTransport harness, so tests never touch a network."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest

from epay import AsyncEpay, Epay

API_KEY = "sk_test_0123456789abcdef"
WEBHOOK_SECRET = "whsec_test_secret"


class Recorder:
    """Captures the requests a client made."""

    def __init__(self) -> None:
        self.calls: List[httpx.Request] = []

    def body(self, index: int = 0) -> Any:
        """The parsed JSON body of a captured request."""
        content = self.calls[index].content
        return json.loads(content) if content else None

    def url(self, index: int = 0) -> httpx.URL:
        return self.calls[index].url

    def header(self, name: str, index: int = 0) -> Optional[str]:
        return self.calls[index].headers.get(name)

    def __len__(self) -> int:
        return len(self.calls)


def make_transport(
    replies: List[Any], recorder: Recorder
) -> Callable[[httpx.Request], httpx.Response]:
    """Builds a handler that answers with each reply in turn.

    A reply is a dict of ``{"status", "json", "headers"}``, or a callable taking
    the request. Running past the end of the script fails loudly.
    """
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.calls.append(request)
        if not queue:
            raise AssertionError(f"unexpected extra request {request.method} {request.url}")

        reply = queue.pop(0)
        if callable(reply):
            return reply(request)

        status = reply.get("status", 200)
        headers: Dict[str, str] = reply.get("headers", {})

        if status == 204 or "json" not in reply:
            return httpx.Response(status, headers=headers)
        if isinstance(reply["json"], str):
            return httpx.Response(status, text=reply["json"], headers=headers)
        return httpx.Response(status, json=reply["json"], headers=headers)

    return handler


@pytest.fixture
def client_factory():
    """Builds a sync Epay wired to a scripted transport, with retries off."""
    created: List[Epay] = []

    def factory(replies: List[Any], **kwargs: Any):
        recorder = Recorder()
        http_client = httpx.Client(transport=httpx.MockTransport(make_transport(replies, recorder)))
        kwargs.setdefault("max_retries", 0)
        client = Epay(API_KEY, http_client=http_client, **kwargs)
        created.append(client)
        return client, recorder

    yield factory

    for client in created:
        client.close()


@pytest.fixture
def async_client_factory():
    """Builds an AsyncEpay wired to a scripted transport, with retries off."""
    created: List[AsyncEpay] = []

    def factory(replies: List[Any], **kwargs: Any):
        recorder = Recorder()
        http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(make_transport(replies, recorder))
        )
        kwargs.setdefault("max_retries", 0)
        client = AsyncEpay(API_KEY, http_client=http_client, **kwargs)
        created.append(client)
        return client, recorder

    return factory


SESSION = {
    "reference": "PAB12CD3420260813",
    "checkoutUrl": "https://checkout.epayethiopia.com/pay/PAB12CD3420260813",
    "status": "success",
    "expiresAt": "2026-08-13T12:30:00.000Z",
}


def transaction(reference: str = "PAB12CD3420260813", status: str = "completed") -> Dict[str, Any]:
    """A transaction object matching the documented shape."""
    return {
        "reference": reference,
        "merchantReference": "order_123",
        "status": status,
        "amount": "250.00",
        "currencyCode": "ETB",
        "paidAt": "2026-08-13T11:47:00.000Z" if status == "completed" else None,
        "createdAt": "2026-08-13T11:30:00.000Z",
    }
