"""Client configuration: option resolution and API-key inspection."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

from ._types import EpayMode
from .errors import EpayConfigError

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_RETRIES",
    "Config",
    "mode_from_api_key",
    "resolve_config",
]

#: Default API root.
DEFAULT_BASE_URL = "https://api.epayethiopia.com/v1"

#: Default per-attempt timeout, in seconds.
DEFAULT_TIMEOUT = 30.0

#: Default number of retries after the initial attempt.
DEFAULT_MAX_RETRIES = 2


@dataclass(frozen=True)
class Config:
    """Fully resolved client configuration."""

    api_key: str
    base_url: str
    timeout: float
    max_retries: int
    webhook_secret: Optional[str] = None
    default_headers: Dict[str, str] = field(default_factory=dict)
    mode: Optional[EpayMode] = None


def mode_from_api_key(api_key: str) -> Optional[EpayMode]:
    """Derives the traffic mode from a key prefix.

    Returns ``None`` for an ``sk_``-prefixed key with an unrecognised
    environment segment, so a future key format does not break the client.
    """
    if api_key.startswith("sk_live_"):
        return "live"
    if api_key.startswith("sk_test_"):
        return "sandbox"
    return None


def resolve_config(
    api_key: Optional[str] = None,
    *,
    webhook_secret: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
    default_headers: Optional[Dict[str, str]] = None,
) -> Config:
    """Validates and fills in every option, reading environment fallbacks.

    Raises:
        EpayConfigError: if no API key is available, the key is clearly not a
            secret key, or an option is out of range.
    """
    key = (api_key or os.environ.get("EPAY_SECRET_KEY") or "").strip()

    if not key:
        raise EpayConfigError(
            "Missing ePay API key. Pass api_key=... or set the EPAY_SECRET_KEY "
            "environment variable."
        )
    if not key.startswith("sk_"):
        raise EpayConfigError(
            'Invalid ePay API key: expected a secret key beginning with "sk_live_" or '
            '"sk_test_". Secret keys are found in the dashboard under '
            "Developers -> API Keys."
        )

    resolved_timeout = DEFAULT_TIMEOUT if timeout is None else float(timeout)
    if resolved_timeout <= 0:
        raise EpayConfigError(f"timeout must be a positive number of seconds, received {timeout!r}")

    resolved_retries = DEFAULT_MAX_RETRIES if max_retries is None else int(max_retries)
    if resolved_retries < 0:
        raise EpayConfigError(
            f"max_retries must be a non-negative integer, received {max_retries!r}"
        )

    root = (base_url or os.environ.get("EPAY_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")

    return Config(
        api_key=key,
        base_url=root,
        timeout=resolved_timeout,
        max_retries=resolved_retries,
        webhook_secret=webhook_secret or os.environ.get("EPAY_WEBHOOK_SECRET") or None,
        default_headers=dict(default_headers or {}),
        mode=mode_from_api_key(key),
    )
