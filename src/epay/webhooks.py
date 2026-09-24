"""Webhook signature verification and event parsing."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Optional, Union

from ._types import WEBHOOK_EVENT_TYPES, WebhookEvent
from .errors import EpayConfigError, EpayValidationError, EpayWebhookSignatureError

__all__ = [
    "SIGNATURE_HEADER",
    "sign_webhook_payload",
    "verify_webhook_signature",
    "construct_webhook_event",
    "is_known_webhook_event",
    "Webhooks",
]

#: Header ePay signs every delivery with.
SIGNATURE_HEADER = "X-Epay-Signature"

_SIGNATURE_PREFIX = "sha256="
_HEX_PATTERN = re.compile(r"^[0-9a-f]+$", re.IGNORECASE)

RawBody = Union[str, bytes, bytearray]


def _to_bytes(payload: RawBody) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return bytes(payload)


def _normalize_signature(header: Optional[str]) -> Optional[str]:
    """Reduces a header value to a bare lowercase hex digest."""
    if not isinstance(header, str):
        return None

    trimmed = header.strip()
    if trimmed.lower().startswith(_SIGNATURE_PREFIX):
        trimmed = trimmed[len(_SIGNATURE_PREFIX) :]

    if not trimmed or not _HEX_PATTERN.match(trimmed):
        return None
    return trimmed.lower()


def sign_webhook_payload(payload: RawBody, secret: str) -> str:
    """Computes the expected hex signature for a payload.

    Useful for generating fixtures in your own tests; ePay does the same
    computation over the raw bytes it sends.
    """
    if not secret:
        raise EpayConfigError("A webhook secret is required to sign a payload.")
    return hmac.new(secret.encode("utf-8"), _to_bytes(payload), hashlib.sha256).hexdigest()


def verify_webhook_signature(
    payload: RawBody, signature_header: Optional[str], secret: str
) -> bool:
    """Checks an ``X-Epay-Signature`` header against the raw request body.

    Pass the **raw** body, never a re-serialized object: ``json.dumps`` of a
    parsed payload may reorder keys or change whitespace, which changes the
    digest and rejects valid deliveries. The comparison is constant-time.
    """
    received = _normalize_signature(signature_header)
    if received is None:
        return False

    expected = sign_webhook_payload(payload, secret)
    return hmac.compare_digest(received, expected)


def construct_webhook_event(
    payload: RawBody, signature_header: Optional[str], secret: str
) -> WebhookEvent:
    """Verifies a delivery and returns the parsed event.

    This is the entry point to use in a webhook handler: it fails closed, so any
    event it returns had a valid signature.

    Raises:
        EpayWebhookSignatureError: if the header is missing or does not match.
        EpayValidationError: if the verified body is not a JSON object.
    """
    if _normalize_signature(signature_header) is None:
        raise EpayWebhookSignatureError(
            f'Missing or malformed {SIGNATURE_HEADER} header. Expected "{_SIGNATURE_PREFIX}<hex>".'
        )
    if not verify_webhook_signature(payload, signature_header, secret):
        raise EpayWebhookSignatureError(
            f"{SIGNATURE_HEADER} does not match the request body. Verify you are "
            "using the raw request body and the webhook secret from "
            "Developers -> Webhooks."
        )

    text = payload if isinstance(payload, str) else _to_bytes(payload).decode("utf-8", "replace")

    try:
        parsed = json.loads(text)
    except ValueError as error:
        raise EpayValidationError(
            "Webhook body passed verification but is not valid JSON."
        ) from error

    if not isinstance(parsed, dict):
        raise EpayValidationError("Webhook body passed verification but is not a JSON object.")

    return parsed  # type: ignore[return-value]


def is_known_webhook_event(event: WebhookEvent) -> bool:
    """Whether the event name is one this SDK version documents."""
    return event.get("event") in WEBHOOK_EVENT_TYPES


class Webhooks:
    """Webhook helpers bound to the secret configured on a client."""

    def __init__(self, secret: Optional[str]) -> None:
        self._secret = secret

    @property
    def configured(self) -> bool:
        """Whether a webhook secret is configured."""
        return bool(self._secret)

    def _require_secret(self, override: Optional[str]) -> str:
        secret = override or self._secret
        if not secret:
            raise EpayConfigError(
                "No webhook secret configured. Pass webhook_secret=... to the client, "
                "set EPAY_WEBHOOK_SECRET, or supply the secret to this call."
            )
        return secret

    def sign(self, payload: RawBody, secret: Optional[str] = None) -> str:
        """See :func:`sign_webhook_payload`."""
        return sign_webhook_payload(payload, self._require_secret(secret))

    def verify(
        self,
        payload: RawBody,
        signature_header: Optional[str],
        secret: Optional[str] = None,
    ) -> bool:
        """See :func:`verify_webhook_signature`."""
        return verify_webhook_signature(payload, signature_header, self._require_secret(secret))

    def construct_event(
        self,
        payload: RawBody,
        signature_header: Optional[str],
        secret: Optional[str] = None,
    ) -> WebhookEvent:
        """See :func:`construct_webhook_event`."""
        return construct_webhook_event(payload, signature_header, self._require_secret(secret))
