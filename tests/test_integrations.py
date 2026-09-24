"""Framework webhook helpers, exercised against fake request objects.

The helpers are duck-typed, so these tests cover them without installing Flask,
Django, or FastAPI.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from epay import EpayValidationError, EpayWebhookSignatureError
from epay.integrations import asgi as asgi_integration
from epay.integrations import django as django_integration
from epay.integrations import flask as flask_integration

SECRET = "whsec_test_secret"
PAYLOAD = json.dumps(
    {"event": "payment.success", "reference": "PAB12CD3420260813", "status": "completed"}
)


def signature(payload: str = PAYLOAD, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


class Headers(dict):
    """Case-insensitive header mapping, as every framework provides."""

    def get(self, key, default=None):  # type: ignore[override]
        for name, value in self.items():
            if name.lower() == key.lower():
                return value
        return default


class FlaskRequest:
    """Stands in for flask.request."""

    def __init__(self, body: bytes, sig: str | None) -> None:
        self._body = body
        self.headers = Headers({} if sig is None else {"X-Epay-Signature": sig})

    def get_data(self) -> bytes:
        return self._body


class DjangoRequest:
    """Stands in for django.http.HttpRequest."""

    def __init__(self, body: bytes, sig: str | None, *, modern_headers: bool = True) -> None:
        self.body = body
        if modern_headers:
            self.headers = Headers({} if sig is None else {"X-Epay-Signature": sig})
            self.META = {}
        else:
            # Django < 2.2 only exposed META.
            self.META = {} if sig is None else {"HTTP_X_EPAY_SIGNATURE": sig}


class AsgiRequest:
    """Stands in for starlette.requests.Request."""

    def __init__(self, body: bytes, sig: str | None) -> None:
        self._body = body
        self.headers = Headers({} if sig is None else {"x-epay-signature": sig})

    async def body(self) -> bytes:
        return self._body


# --- Flask ------------------------------------------------------------------


def test_flask_verifies_a_genuine_delivery():
    request = FlaskRequest(PAYLOAD.encode(), signature())
    event = flask_integration.construct_event_from_request(request, SECRET)
    assert event["reference"] == "PAB12CD3420260813"


def test_flask_rejects_a_tampered_body():
    request = FlaskRequest(PAYLOAD.replace("completed", "failed").encode(), signature())
    with pytest.raises(EpayWebhookSignatureError):
        flask_integration.construct_event_from_request(request, SECRET)


def test_flask_rejects_a_missing_header():
    request = FlaskRequest(PAYLOAD.encode(), None)
    with pytest.raises(EpayWebhookSignatureError, match="Missing or malformed"):
        flask_integration.construct_event_from_request(request, SECRET)


def test_flask_decorator_passes_the_event_to_the_view():
    request = FlaskRequest(PAYLOAD.encode(), signature())
    seen = []

    @flask_integration.epay_webhook(SECRET, request_getter=lambda: request)
    def view(event):
        seen.append(event)
        return "ok"

    assert view() == "ok"
    assert seen[0]["reference"] == "PAB12CD3420260813"


def test_flask_decorator_raises_before_the_view_runs():
    request = FlaskRequest(PAYLOAD.encode(), "sha256=00")
    called = []

    @flask_integration.epay_webhook(SECRET, request_getter=lambda: request)
    def view(event):
        called.append(event)

    with pytest.raises(EpayWebhookSignatureError):
        view()
    assert not called


def test_flask_decorator_preserves_view_metadata():
    @flask_integration.epay_webhook(SECRET, request_getter=lambda: None)
    def my_webhook_view(event):
        """Original docstring."""

    assert my_webhook_view.__name__ == "my_webhook_view"
    assert my_webhook_view.__doc__ == "Original docstring."


# --- Django -----------------------------------------------------------------


def test_django_verifies_via_modern_headers():
    request = DjangoRequest(PAYLOAD.encode(), signature())
    event = django_integration.construct_event_from_request(request, SECRET)
    assert event["reference"] == "PAB12CD3420260813"


def test_django_falls_back_to_meta():
    request = DjangoRequest(PAYLOAD.encode(), signature(), modern_headers=False)
    event = django_integration.construct_event_from_request(request, SECRET)
    assert event["reference"] == "PAB12CD3420260813"


def test_django_rejects_a_bad_signature():
    request = DjangoRequest(PAYLOAD.encode(), "sha256=deadbeef")
    with pytest.raises(EpayWebhookSignatureError):
        django_integration.construct_event_from_request(request, SECRET)


def test_django_decorator_passes_request_and_event():
    request = DjangoRequest(PAYLOAD.encode(), signature())
    seen = {}

    @django_integration.epay_webhook(SECRET)
    def view(req, event):
        seen["request"] = req
        seen["event"] = event
        return "ok"

    assert view(request) == "ok"
    assert seen["request"] is request
    assert seen["event"]["reference"] == "PAB12CD3420260813"


def test_django_rejects_a_non_object_body():
    body = b"not json at all"
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    request = DjangoRequest(body, sig)
    with pytest.raises(EpayValidationError):
        django_integration.construct_event_from_request(request, SECRET)


# --- ASGI -------------------------------------------------------------------


async def test_asgi_verifies_a_genuine_delivery():
    request = AsgiRequest(PAYLOAD.encode(), signature())
    event = await asgi_integration.construct_event_from_request(request, SECRET)
    assert event["reference"] == "PAB12CD3420260813"


async def test_asgi_rejects_a_tampered_body():
    request = AsgiRequest(PAYLOAD.replace("completed", "failed").encode(), signature())
    with pytest.raises(EpayWebhookSignatureError):
        await asgi_integration.construct_event_from_request(request, SECRET)


async def test_asgi_verifier_is_reusable_across_requests():
    verifier = asgi_integration.EpayWebhookVerifier(SECRET)

    first = await verifier(AsgiRequest(PAYLOAD.encode(), signature()))
    second = await verifier(AsgiRequest(PAYLOAD.encode(), signature()))

    assert first["reference"] == second["reference"] == "PAB12CD3420260813"

    with pytest.raises(EpayWebhookSignatureError):
        await verifier(AsgiRequest(PAYLOAD.encode(), None))
