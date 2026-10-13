"""Webhook signing, verification, and event parsing."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from epay import (
    Epay,
    EpayConfigError,
    EpayValidationError,
    EpayWebhookSignatureError,
    construct_webhook_event,
    is_known_webhook_event,
    sign_webhook_payload,
    verify_webhook_signature,
)
from epay.webhooks import SIGNATURE_HEADER

SECRET = "whsec_test_secret"

PAYLOAD = json.dumps(
    {
        "event": "payment.success",
        "mode": "live",
        "reference": "PAB12CD3420260813",
        "merchantReference": "order_123",
        "amount": "250.00",
        "serviceFee": "7.50",
        "currency": "ETB",
        "status": "completed",
        "paymentMethod": "telebirr",
        "customer": {
            "name": "Abebe Bikila",
            "email": "abebe@example.com",
            "phone": "+251911234567",
        },
        "paidAt": "2026-08-13T11:47:00.000Z",
        "createdAt": "2026-08-13T11:30:00.000Z",
    }
)


def header(payload=PAYLOAD, secret=SECRET):
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return "sha256=" + digest


def test_the_header_name_matches_the_docs():
    assert SIGNATURE_HEADER == "X-Epay-Signature"


def test_signing_matches_a_hand_rolled_hmac():
    expected = hmac.new(SECRET.encode(), PAYLOAD.encode(), hashlib.sha256).hexdigest()
    assert sign_webhook_payload(PAYLOAD, SECRET) == expected


def test_a_genuine_delivery_verifies():
    assert verify_webhook_signature(PAYLOAD, header(), SECRET) is True


def test_the_prefix_is_optional_and_case_insensitive():
    hex_digest = sign_webhook_payload(PAYLOAD, SECRET)
    assert verify_webhook_signature(PAYLOAD, hex_digest, SECRET)
    assert verify_webhook_signature(PAYLOAD, "SHA256=" + hex_digest.upper(), SECRET)
    assert verify_webhook_signature(PAYLOAD, "  sha256=" + hex_digest + "  ", SECRET)


def test_bytes_bodies_verify_identically_to_strings():
    assert verify_webhook_signature(PAYLOAD.encode(), header(), SECRET)
    assert verify_webhook_signature(bytearray(PAYLOAD.encode()), header(), SECRET)


def test_a_tampered_body_or_wrong_secret_fails():
    assert not verify_webhook_signature(PAYLOAD.replace("250.00", "1.00"), header(), SECRET)
    assert not verify_webhook_signature(PAYLOAD, header(PAYLOAD, "wrong"), SECRET)
    assert not verify_webhook_signature(PAYLOAD, "sha256=abc", SECRET)


@pytest.mark.parametrize("value", [None, "", "sha256=", "not-hex!!", "sha256=zzzz", 42])
def test_a_missing_or_malformed_header_fails_without_raising(value):
    assert verify_webhook_signature(PAYLOAD, value, SECRET) is False


def test_construct_event_returns_the_parsed_event():
    event = construct_webhook_event(PAYLOAD, header(), SECRET)
    assert event["event"] == "payment.success"
    assert event["reference"] == "PAB12CD3420260813"
    assert event["customer"]["phone"] == "+251911234567"
    assert is_known_webhook_event(event)


def test_construct_event_fails_closed():
    with pytest.raises(EpayWebhookSignatureError):
        construct_webhook_event(PAYLOAD, None, SECRET)
    with pytest.raises(EpayWebhookSignatureError):
        construct_webhook_event(PAYLOAD, "sha256=00", SECRET)
    with pytest.raises(EpayWebhookSignatureError):
        construct_webhook_event(PAYLOAD.replace("250.00", "1.00"), header(), SECRET)


def test_a_verified_body_that_is_not_an_object_is_rejected():
    for body in ["this is not json", "[1,2,3]", '"a string"']:
        with pytest.raises(EpayValidationError):
            construct_webhook_event(body, header(body), SECRET)


def test_an_unknown_event_name_verifies_but_is_flagged():
    body = json.dumps({"event": "payment.disputed", "reference": "P1"})
    event = construct_webhook_event(body, header(body), SECRET)
    assert event["event"] == "payment.disputed"
    assert not is_known_webhook_event(event)


def test_client_webhooks_uses_the_configured_secret():
    epay = Epay("sk_test_abc", webhook_secret=SECRET)
    assert epay.webhooks.configured
    assert epay.webhooks.verify(PAYLOAD, header())
    assert epay.webhooks.construct_event(PAYLOAD, header())["reference"] == "PAB12CD3420260813"
    epay.close()


def test_client_webhooks_explains_itself_without_a_secret(monkeypatch):
    monkeypatch.delenv("EPAY_WEBHOOK_SECRET", raising=False)
    epay = Epay("sk_test_abc")
    assert not epay.webhooks.configured
    with pytest.raises(EpayConfigError):
        epay.webhooks.verify(PAYLOAD, header())
    # A per-call secret still works.
    assert epay.webhooks.verify(PAYLOAD, header(), SECRET)
    epay.close()


def test_signing_requires_a_secret():
    with pytest.raises(EpayConfigError):
        sign_webhook_payload(PAYLOAD, "")


def test_direct_payment_fields_pass_through():
    body = json.dumps(
        {
            "event": "payment.failed",
            "reference": "A3BX72KP",
            "pspCode": "TELEBIRR",
            "reason": "Customer cancelled",
        }
    )
    event = construct_webhook_event(body, header(body), SECRET)

    assert event["pspCode"] == "TELEBIRR"
    assert event["reason"] == "Customer cancelled"
