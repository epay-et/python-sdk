"""Local validation: amounts, phone numbers, currencies."""

from __future__ import annotations

from decimal import Decimal

import pytest

from epay import EpayValidationError, format_amount, normalize_currency, normalize_phone
from epay.helpers import MAX_AMOUNT, format_date_param, mask_secret


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("250.00", "250.00"),
        ("250", "250.00"),
        ("250.5", "250.50"),
        ("  42.10  ", "42.10"),
        (250, "250.00"),
        (1, "1.00"),
        (Decimal("250"), "250.00"),
        (Decimal("0.01"), "0.01"),
        (1.5, "1.50"),
        ("999999999.99", "999999999.99"),
        (MAX_AMOUNT, "999999999.99"),
    ],
)
def test_format_amount_normalizes_to_two_decimals(value, expected):
    assert format_amount(value) == expected


def test_format_amount_rounds_half_up():
    assert format_amount(Decimal("10.005")) == "10.01"
    assert format_amount(Decimal("10.004")) == "10.00"


@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        "0",
        "0.00",
        "-5.00",
        "1.234",  # 3 decimal places
        "1000000000.00",  # 10 integer digits
        Decimal("1000000000"),
        "abc",
        "",
        "1e3",
        float("nan"),
        float("inf"),
        True,  # bool is an int subclass, almost never intended
        None,
        [],
    ],
)
def test_format_amount_rejects_what_the_api_would(value):
    with pytest.raises(EpayValidationError):
        format_amount(value)


@pytest.mark.parametrize(
    "value",
    [
        "+251911234567",
        "251911234567",
        "0911234567",
        "911234567",
        "+251 91 123 4567",
        "0911-234-567",
        "(0911) 234 567",
    ],
)
def test_normalize_phone_accepts_every_documented_form(value):
    assert normalize_phone(value) == "+251911234567"


def test_normalize_phone_accepts_the_safaricom_range():
    assert normalize_phone("0711234567") == "+251711234567"


@pytest.mark.parametrize(
    "magic",
    ["251900000000", "251900000001", "251900000002", "251900000003", "251900000004"],
)
def test_normalize_phone_handles_the_sandbox_magic_numbers(magic):
    """From the Test Accounts reference."""
    assert normalize_phone(magic) == "+" + magic


@pytest.mark.parametrize(
    "value",
    ["+251811234567", "0811234567", "09112345678", "091123456", "", "+1 555 0100", "abc"],
)
def test_normalize_phone_rejects_non_ethiopian_mobiles(value):
    with pytest.raises(EpayValidationError):
        normalize_phone(value)


def test_normalize_currency_uppercases_and_validates():
    assert normalize_currency("etb") == "ETB"
    assert normalize_currency(" ETB ") == "ETB"
    for bad in ["ET", "ETBB", "123", ""]:
        with pytest.raises(EpayValidationError):
            normalize_currency(bad)


def test_format_date_param_accepts_dates_and_strings():
    from datetime import date, datetime

    assert format_date_param(date(2026, 8, 1), "from") == "2026-08-01"
    assert format_date_param(datetime(2026, 8, 1, 13, 30), "from") == "2026-08-01"
    assert format_date_param("2026-08-01", "from") == "2026-08-01"
    with pytest.raises(EpayValidationError):
        format_date_param("  ", "from")


def test_mask_secret_hides_the_middle():
    assert mask_secret("sk_live_supersecretvalue1234") == "sk_live_…1234"
    assert mask_secret("short") == "***"
