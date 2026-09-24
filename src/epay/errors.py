"""Error hierarchy for the ePay Business API.

Every failure raised by this SDK is an :class:`EpayError`. HTTP failures are
:class:`EpayAPIError` subclasses keyed by status code, so callers can branch on
``except`` clauses instead of inspecting numbers.
"""

from __future__ import annotations

import email.utils
import time
from typing import Any, Mapping, Optional

__all__ = [
    "EpayError",
    "EpayConfigError",
    "EpayValidationError",
    "EpayWebhookSignatureError",
    "EpayConnectionError",
    "EpayTimeoutError",
    "EpayAPIError",
    "EpayBadRequestError",
    "EpayAuthenticationError",
    "EpayPermissionDeniedError",
    "EpayNotFoundError",
    "EpayConflictError",
    "EpayUnprocessableEntityError",
    "EpayRateLimitError",
    "EpayServerError",
    "parse_error_message",
    "parse_retry_after",
]


class EpayError(Exception):
    """Base class for every error raised by the SDK."""


class EpayConfigError(EpayError):
    """The client was constructed with unusable options."""


class EpayValidationError(EpayError, ValueError):
    """A value failed local validation, so no request was sent.

    Also a :class:`ValueError`, so existing ``except ValueError`` handlers keep
    working.
    """


class EpayWebhookSignatureError(EpayError):
    """A webhook payload failed signature verification."""


class EpayConnectionError(EpayError):
    """The request never produced an HTTP response."""


class EpayTimeoutError(EpayConnectionError):
    """The request exceeded the configured timeout."""


class EpayAPIError(EpayError):
    """Base class for any non-2xx HTTP response.

    Attributes:
        status: HTTP status code.
        body: Parsed response body, or the raw text when it was not JSON.
        headers: Response headers, lowercased.
        request: Method and path of the originating request.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int,
        body: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        request: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.headers = dict(headers or {})
        self.request = request

    @property
    def message(self) -> str:
        """The error message, without the request prefix stripped."""
        return str(self)


class EpayBadRequestError(EpayAPIError):
    """``400`` — the request was rejected as invalid."""


class EpayAuthenticationError(EpayAPIError):
    """``401`` — the API key is missing, malformed, invalid, or revoked."""


class EpayPermissionDeniedError(EpayAPIError):
    """``403`` — the caller IP is not whitelisted, or the key lacks a permission."""


class EpayNotFoundError(EpayAPIError):
    """``404`` — no such transaction, or no payment source on the account."""


class EpayConflictError(EpayAPIError):
    """``409`` — the request conflicts with the current state of the resource."""


class EpayUnprocessableEntityError(EpayAPIError):
    """``422`` — well-formed but semantically rejected."""


class EpayServerError(EpayAPIError):
    """``5xx`` — the API failed to process a valid request."""


class EpayRateLimitError(EpayAPIError):
    """``429`` — the 100 requests / 60s per-key budget is exhausted.

    The SDK already retries these, so receiving one means the retry budget was
    also exhausted.
    """

    @property
    def retry_after_seconds(self) -> Optional[float]:
        """Seconds to wait before retrying, from the ``Retry-After`` header."""
        return parse_retry_after(self.headers.get("retry-after"))


_STATUS_MAP = {
    400: EpayBadRequestError,
    401: EpayAuthenticationError,
    403: EpayPermissionDeniedError,
    404: EpayNotFoundError,
    409: EpayConflictError,
    422: EpayUnprocessableEntityError,
    429: EpayRateLimitError,
}


def error_from_response(
    *,
    status: int,
    body: Any,
    headers: Optional[Mapping[str, str]] = None,
    request: str = "",
) -> EpayAPIError:
    """Builds the most specific error class for a response."""
    message = parse_error_message(body, status)
    detail = f"{request} failed with {status}: {message}" if request else message

    cls = _STATUS_MAP.get(status)
    if cls is None:
        cls = EpayServerError if status >= 500 else EpayAPIError

    return cls(detail, status=status, body=body, headers=headers, request=request)


def _flatten_message(value: Any) -> Optional[str]:
    """Reduces a message field to a string, joining validation lists."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [item for item in value if isinstance(item, str)]
        if parts:
            return "; ".join(parts)
    return None


def parse_error_message(body: Any, status: int) -> str:
    """Extracts a human-readable message from an error body.

    The API uses two envelopes: ``{"status": "error", "data": {"message": ...}}``
    on the transaction endpoints and ``{"statusCode", "message", "error"}`` on
    the provider endpoints, where ``message`` may be a list of validation
    strings.
    """
    fallback = f"HTTP {status}"

    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        return body.strip() or fallback
    if not isinstance(body, dict):
        return fallback

    data = body.get("data")
    if isinstance(data, dict):
        nested = _flatten_message(data.get("message"))
        if nested:
            return nested

    flattened = _flatten_message(body.get("message"))
    if flattened:
        return flattened

    error = body.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()

    return fallback


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parses a ``Retry-After`` header, as seconds or an HTTP-date."""
    if not value:
        return None

    try:
        seconds = float(value)
    except ValueError:
        pass
    else:
        return seconds if seconds >= 0 else None

    parsed = email.utils.parsedate_to_datetime(value)
    if parsed is None:
        return None
    return max(0.0, parsed.timestamp() - time.time())
