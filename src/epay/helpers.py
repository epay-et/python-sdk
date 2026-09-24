"""Validation and normalization helpers for request values."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Union

from .errors import EpayValidationError

__all__ = [
    "MAX_AMOUNT",
    "MAX_LIST_RANGE_DAYS",
    "format_amount",
    "normalize_phone",
    "normalize_currency",
    "format_date_param",
    "require_reference",
    "mask_secret",
]

#: Largest amount the API accepts.
MAX_AMOUNT = Decimal("999999999.99")

#: Maximum span the transaction list endpoint allows between ``from`` and ``to``.
MAX_LIST_RANGE_DAYS = 90

_AMOUNT_PATTERN = re.compile(r"^\d{1,9}(\.\d{1,2})?$")
_SEPARATORS = re.compile(r"[\s()\-.]")

AmountInput = Union[str, int, float, Decimal]


def format_amount(value: AmountInput) -> str:
    """Normalizes an amount to the numeric string the API expects.

    The result always carries exactly two decimal places, so ``250``,
    ``"250"``, and ``Decimal("250.0")`` all become ``"250.00"``.

    Prefer ``str`` or :class:`~decimal.Decimal`. A ``float`` is accepted and
    rounded half-up to two places, but binary floats cannot represent every
    decimal amount exactly, so money is better kept out of them.

    Raises:
        EpayValidationError: if the value is not a positive amount in range.
    """
    if isinstance(value, bool):  # bool is an int subclass; almost never intended
        raise EpayValidationError("amount must be a number or string, received a bool")

    if isinstance(value, float):
        try:
            candidate = Decimal(str(value))
        except InvalidOperation as error:
            raise EpayValidationError(
                f"amount must be a finite number, received {value!r}"
            ) from error
        if not candidate.is_finite():
            raise EpayValidationError(f"amount must be a finite number, received {value!r}")
        candidate = candidate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif isinstance(value, (int, Decimal)):
        candidate = Decimal(value)
        if not candidate.is_finite():
            raise EpayValidationError(f"amount must be a finite number, received {value!r}")
        candidate = candidate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif isinstance(value, str):
        text = value.strip()
        if not _AMOUNT_PATTERN.match(text):
            raise EpayValidationError(
                "amount must be a positive numeric string with at most 9 integer digits "
                f"and 2 decimal places, received {value!r}"
            )
        candidate = Decimal(text)
    else:
        raise EpayValidationError(
            f"amount must be a str, int, float, or Decimal, received {value!r}"
        )

    if candidate <= 0:
        raise EpayValidationError(f"amount must be greater than 0, received {value!r}")
    if candidate > MAX_AMOUNT:
        raise EpayValidationError(f"amount must not exceed {MAX_AMOUNT}, received {value!r}")

    # No separate integer-digit check is needed: MAX_AMOUNT is the largest value
    # with 9 integer digits, so the bound above already enforces the limit.

    return f"{candidate:.2f}"


def normalize_phone(value: str) -> str:
    """Normalizes an Ethiopian mobile number to ``+251XXXXXXXXX``.

    Accepts local (``0911234567``), bare national (``911234567``), and
    international (``251911234567``, ``+251911234567``) forms, with spaces,
    dashes, and parentheses anywhere. Both Ethio Telecom (``9…``) and Safaricom
    Ethiopia (``7…``) ranges are recognised.

    Raises:
        EpayValidationError: if the value is not a recognised Ethiopian mobile number.
    """
    if not isinstance(value, str):
        raise EpayValidationError(f"customerPhone must be a string, received {value!r}")

    cleaned = _SEPARATORS.sub("", value)
    digits = cleaned[1:] if cleaned.startswith("+") else cleaned

    if not digits.isdigit():
        raise EpayValidationError(
            f"customerPhone must contain only digits and separators, received {value!r}"
        )

    subscriber = None
    if re.match(r"^251[79]\d{8}$", digits):
        subscriber = digits[3:]
    elif re.match(r"^0[79]\d{8}$", digits):
        subscriber = digits[1:]
    elif re.match(r"^[79]\d{8}$", digits):
        subscriber = digits

    if subscriber is None:
        raise EpayValidationError(
            "customerPhone must be an Ethiopian mobile number such as +251911234567 "
            f"or 0911234567, received {value!r}"
        )

    return "+251" + subscriber


def normalize_currency(value: str, field: str = "currencyCode") -> str:
    """Validates a 3-letter ISO 4217 code and uppercases it."""
    if not isinstance(value, str):
        raise EpayValidationError(f"{field} must be a string, received {value!r}")

    text = value.strip().upper()
    if not re.match(r"^[A-Z]{3}$", text):
        raise EpayValidationError(
            f"{field} must be a 3-letter ISO 4217 code such as ETB, received {value!r}"
        )
    return text


def format_date_param(value: Union[str, date, datetime], field: str) -> str:
    """Normalizes a date to the ``YYYY-MM-DD`` form the list filters take."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise EpayValidationError(f"{field} must not be empty")
        return text
    raise EpayValidationError(f"{field} must be a str, date, or datetime, received {value!r}")


def require_reference(value: str) -> str:
    """Validates a transaction reference is present and trims it."""
    if not isinstance(value, str) or not value.strip():
        raise EpayValidationError("reference must be a non-empty string")
    return value.strip()


def mask_secret(value: str) -> str:
    """Masks a secret so it can be logged or shown in a traceback safely."""
    if len(value) <= 12:
        return "***"
    return f"{value[:8]}…{value[-4:]}"
