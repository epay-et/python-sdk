"""Webhook verification for Django.

::

    from django.http import HttpResponse, HttpResponseForbidden
    from django.views.decorators.csrf import csrf_exempt
    from epay import EpayWebhookSignatureError
    from epay.integrations.django import construct_event_from_request

    @csrf_exempt
    def epay_webhook(request):
        try:
            event = construct_event_from_request(request, settings.EPAY_WEBHOOK_SECRET)
        except EpayWebhookSignatureError as error:
            return HttpResponseForbidden(str(error))

        enqueue(event)  # acknowledge fast, process later
        return HttpResponse(status=200)

``@csrf_exempt`` is required: ePay is a third party and sends no CSRF token.

The decorator form handles the rejection for you::

    @csrf_exempt
    @epay_webhook(secret=settings.EPAY_WEBHOOK_SECRET)
    def epay_webhook(request, event):
        enqueue(event)
        return HttpResponse(status=200)
"""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar, cast

from .._types import WebhookEvent
from ..webhooks import SIGNATURE_HEADER, construct_webhook_event

__all__ = ["construct_event_from_request", "epay_webhook"]

F = TypeVar("F", bound=Callable[..., Any])


def construct_event_from_request(request: Any, secret: str) -> WebhookEvent:
    """Verifies a Django request and returns the parsed event.

    Uses ``request.body``, the raw bytes Django read. Do not access
    ``request.POST`` on this view first: for some content types that consumes
    the stream and ``request.body`` then raises.

    Raises:
        EpayWebhookSignatureError: if the header is missing or does not match.
        EpayValidationError: if the verified body is not a JSON object.
    """
    signature = None

    # Django 2.2+ exposes case-insensitive request.headers; fall back to META.
    headers = getattr(request, "headers", None)
    if headers is not None:
        signature = headers.get(SIGNATURE_HEADER)
    if signature is None:
        meta = getattr(request, "META", {})
        signature = meta.get("HTTP_X_EPAY_SIGNATURE")

    return construct_webhook_event(request.body, signature, secret)


def epay_webhook(secret: str) -> Callable[[F], F]:
    """Decorator that verifies the signature and passes the event to the view.

    The wrapped view is called as ``view(request, event, *args, **kwargs)``.
    Wrap it in ``@csrf_exempt`` as well.
    """

    def decorator(view: F) -> F:
        @functools.wraps(view)
        def wrapper(request: Any, *args: Any, **kwargs: Any) -> Any:
            event = construct_event_from_request(request, secret)
            return view(request, event, *args, **kwargs)

        return cast(F, wrapper)

    return decorator
