"""Webhook verification for Flask and Quart.

::

    from flask import Flask, request, abort
    from epay import EpayWebhookSignatureError
    from epay.integrations.flask import construct_event_from_request

    app = Flask(__name__)

    @app.post("/webhooks/epay")
    def epay_webhook():
        try:
            event = construct_event_from_request(request, os.environ["EPAY_WEBHOOK_SECRET"])
        except EpayWebhookSignatureError as error:
            abort(401, str(error))

        queue.enqueue(event)  # acknowledge fast, process later
        return "", 200

There is also a decorator that does the same and passes the event in::

    @app.post("/webhooks/epay")
    @epay_webhook(secret=os.environ["EPAY_WEBHOOK_SECRET"])
    def epay_webhook(event):
        queue.enqueue(event)
        return "", 200
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Optional, TypeVar, cast

from .._types import WebhookEvent
from ..webhooks import SIGNATURE_HEADER, construct_webhook_event

__all__ = ["construct_event_from_request", "epay_webhook"]

F = TypeVar("F", bound=Callable[..., Any])


def construct_event_from_request(request: Any, secret: str) -> WebhookEvent:
    """Verifies a Flask request and returns the parsed event.

    Uses ``request.get_data()``, which is the raw body Flask buffered -- not the
    output of ``request.get_json()``. Re-serializing parsed JSON can reorder
    keys and change the digest.

    Raises:
        EpayWebhookSignatureError: if the header is missing or does not match.
        EpayValidationError: if the verified body is not a JSON object.
    """
    raw_body = request.get_data()
    signature = request.headers.get(SIGNATURE_HEADER)
    return construct_webhook_event(raw_body, signature, secret)


def epay_webhook(
    secret: str, *, request_getter: Optional[Callable[[], Any]] = None
) -> Callable[[F], F]:
    """Decorator that verifies the signature and passes the event to the view.

    Args:
        secret: The webhook signing secret.
        request_getter: Supplies the request object. Defaults to importing
            Flask's request proxy, so Flask is only required when the decorator
            actually runs.
    """

    def decorator(view: F) -> F:
        @functools.wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if request_getter is not None:
                request = request_getter()
            else:
                # Imported lazily, so Flask is only needed when this runs.
                from flask import request as flask_request  # type: ignore[import-not-found]

                request = flask_request

            event = construct_event_from_request(request, secret)
            return view(event, *args, **kwargs)

        return cast(F, wrapper)

    return decorator
