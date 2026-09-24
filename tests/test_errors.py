"""Error mapping: status codes, both API envelopes, Retry-After."""

from __future__ import annotations

import time
from email.utils import formatdate

import pytest

from epay import (
    EpayAPIError,
    EpayAuthenticationError,
    EpayBadRequestError,
    EpayConflictError,
    EpayError,
    EpayNotFoundError,
    EpayPermissionDeniedError,
    EpayRateLimitError,
    EpayServerError,
)
from epay.errors import error_from_response, parse_error_message


def build(status, body=None, headers=None):
    return error_from_response(
        status=status, body=body, headers=headers or {}, request="GET /transactions"
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, EpayBadRequestError),
        (401, EpayAuthenticationError),
        (403, EpayPermissionDeniedError),
        (404, EpayNotFoundError),
        (409, EpayConflictError),
        (429, EpayRateLimitError),
        (500, EpayServerError),
        (503, EpayServerError),
    ],
)
def test_status_codes_map_to_specific_classes(status, expected):
    error = build(status)
    assert isinstance(error, expected)
    assert isinstance(error, EpayAPIError)
    assert isinstance(error, EpayError)
    assert error.status == status


def test_an_unmapped_4xx_stays_a_plain_api_error():
    assert type(build(418)) is EpayAPIError


def test_the_transaction_envelope_is_unwrapped():
    error = build(
        401, {"status": "error", "data": {"message": "Missing or malformed Authorization header"}}
    )
    assert "Missing or malformed Authorization header" in str(error)
    assert "GET /transactions failed with 401" in str(error)


def test_the_provider_envelope_is_unwrapped():
    error = build(
        401, {"statusCode": 401, "message": "Invalid or inactive API key", "error": "Unauthorized"}
    )
    assert "Invalid or inactive API key" in str(error)


def test_a_list_of_validation_messages_is_joined():
    error = build(
        400, {"statusCode": 400, "message": ["amount must be positive", "currencyCode is required"]}
    )
    assert "amount must be positive; currencyCode is required" in str(error)


def test_a_non_json_or_empty_body_still_yields_a_message():
    assert "Bad Gateway" in str(build(502, "Bad Gateway"))
    assert "HTTP 500" in str(build(500, None))
    assert "HTTP 500" in str(build(500, {}))
    assert "Unauthorized" in str(build(401, {"error": "Unauthorized"}))


def test_errors_carry_the_body_and_headers():
    body = {"status": "error", "data": {"message": "nope"}}
    error = build(400, body, {"x-request-id": "req_1"})
    assert error.body == body
    assert error.headers["x-request-id"] == "req_1"
    assert error.request == "GET /transactions"


def test_rate_limit_exposes_retry_after_as_seconds():
    assert build(429, headers={"retry-after": "30"}).retry_after_seconds == 30.0
    assert build(429).retry_after_seconds is None

    http_date = formatdate(time.time() + 10, usegmt=True)
    delay = build(429, headers={"retry-after": http_date}).retry_after_seconds
    assert delay is not None and delay > 5


def test_parse_error_message_handles_bytes():
    assert parse_error_message(b"upstream boom", 502) == "upstream boom"
