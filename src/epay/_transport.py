"""HTTP transport: request specs, retry policy, and error mapping.

The retry policy and error mapping live here as module-level functions so the
sync and async clients share one implementation and cannot drift apart.
"""

from __future__ import annotations

import json as jsonlib
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from ._config import Config
from ._version import __version__
from .errors import (
    EpayConnectionError,
    EpayTimeoutError,
    error_from_response,
    parse_retry_after,
)

__all__ = ["RequestSpec", "SyncTransport", "AsyncTransport"]

#: Status codes worth a second attempt, alongside anything 5xx.
_RETRYABLE_STATUSES = frozenset({408, 409, 429})

#: Base delay for exponential backoff, in seconds.
_BACKOFF_BASE = 0.5

#: Ceiling for a single backoff delay, in seconds.
_BACKOFF_MAX = 8.0


@dataclass(frozen=True)
class RequestSpec:
    """A single API call, independent of sync or async execution."""

    method: str
    path: str
    params: Optional[Dict[str, Any]] = None
    json: Optional[Dict[str, Any]] = None
    headers: Dict[str, str] = field(default_factory=dict)
    #: Whether a failed attempt may be retried. Defaults to true for GET.
    retryable: Optional[bool] = None

    @property
    def label(self) -> str:
        """Method and path, for error messages."""
        return f"{self.method} {self.path}"

    def is_retryable(self) -> bool:
        if self.retryable is not None:
            return self.retryable
        return self.method == "GET"


def _build_headers(config: Config, spec: RequestSpec) -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.api_key}",
        "User-Agent": f"epay-python/{__version__}",
    }
    headers.update(config.default_headers)
    headers.update(spec.headers)
    if spec.json is not None:
        headers["Content-Type"] = "application/json"
    return headers


def _url(config: Config, spec: RequestSpec) -> str:
    path = spec.path if spec.path.startswith("/") else "/" + spec.path
    return config.base_url + path


def _clean_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drops keys whose value is ``None``, so they are absent from the query."""
    if not params:
        return None
    return {key: value for key, value in params.items() if value is not None}


def _should_retry_status(status: int) -> bool:
    return status >= 500 or status in _RETRYABLE_STATUSES


def _backoff_delay(attempt: int, retry_after: Optional[float]) -> float:
    """Exponential backoff with jitter, honouring ``Retry-After``.

    Jitter keeps concurrent clients from retrying in lockstep.
    """
    if retry_after is not None:
        return float(min(retry_after, _BACKOFF_MAX))
    ceiling = min(_BACKOFF_BASE * (2.0**attempt), _BACKOFF_MAX)
    return ceiling * (0.5 + random.random() * 0.5)


def _parse_body(response: httpx.Response) -> Any:
    """Parses a response body as JSON, falling back to raw text.

    ``204 No Content`` (returned by cancel) and empty bodies become ``None``.
    """
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except (ValueError, jsonlib.JSONDecodeError):
        return response.text


def _handle(response: httpx.Response, spec: RequestSpec) -> Any:
    """Returns the parsed body, or raises the mapped error."""
    if response.is_success:
        return _parse_body(response)

    raise error_from_response(
        status=response.status_code,
        body=_parse_body(response),
        headers={key.lower(): value for key, value in response.headers.items()},
        request=spec.label,
    )


def _translate_transport_error(error: Exception, url: str, timeout: float) -> Exception:
    """Maps an httpx transport failure onto the SDK hierarchy."""
    if isinstance(error, httpx.TimeoutException):
        return EpayTimeoutError(f"Request to {url} timed out after {timeout}s")
    return EpayConnectionError(f"Could not reach the ePay API at {url}: {error}")


class SyncTransport:
    """Issues API calls over a synchronous ``httpx.Client``."""

    def __init__(self, config: Config, http_client: Optional[httpx.Client] = None) -> None:
        self._config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=config.timeout)

    def request(self, spec: RequestSpec) -> Any:
        """Sends a request, retrying transient failures, and returns the body."""
        import time

        url = _url(self._config, spec)
        attempts = self._config.max_retries + 1 if spec.is_retryable() else 1
        last_error: Optional[Exception] = None

        for attempt in range(attempts):
            is_last = attempt == attempts - 1
            try:
                response = self._client.request(
                    spec.method,
                    url,
                    params=_clean_params(spec.params),
                    json=spec.json,
                    headers=_build_headers(self._config, spec),
                    timeout=self._config.timeout,
                )
            except httpx.HTTPError as error:
                last_error = _translate_transport_error(error, url, self._config.timeout)
                if is_last:
                    raise last_error from error
                time.sleep(_backoff_delay(attempt, None))
                continue

            if response.is_success or is_last or not _should_retry_status(response.status_code):
                return _handle(response, spec)

            time.sleep(
                _backoff_delay(attempt, parse_retry_after(response.headers.get("retry-after")))
            )

        raise last_error or EpayConnectionError(f"{spec.label} failed after {attempts} attempts")

    def close(self) -> None:
        """Closes the underlying connection pool, if this transport owns it."""
        if self._owns_client:
            self._client.close()


class AsyncTransport:
    """Issues API calls over an asynchronous ``httpx.AsyncClient``."""

    def __init__(self, config: Config, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=config.timeout)

    async def request(self, spec: RequestSpec) -> Any:
        """Sends a request, retrying transient failures, and returns the body."""
        import asyncio

        url = _url(self._config, spec)
        attempts = self._config.max_retries + 1 if spec.is_retryable() else 1
        last_error: Optional[Exception] = None

        for attempt in range(attempts):
            is_last = attempt == attempts - 1
            try:
                response = await self._client.request(
                    spec.method,
                    url,
                    params=_clean_params(spec.params),
                    json=spec.json,
                    headers=_build_headers(self._config, spec),
                    timeout=self._config.timeout,
                )
            except httpx.HTTPError as error:
                last_error = _translate_transport_error(error, url, self._config.timeout)
                if is_last:
                    raise last_error from error
                await asyncio.sleep(_backoff_delay(attempt, None))
                continue

            if response.is_success or is_last or not _should_retry_status(response.status_code):
                return _handle(response, spec)

            await asyncio.sleep(
                _backoff_delay(attempt, parse_retry_after(response.headers.get("retry-after")))
            )

        raise last_error or EpayConnectionError(f"{spec.label} failed after {attempts} attempts")

    async def aclose(self) -> None:
        """Closes the underlying connection pool, if this transport owns it."""
        if self._owns_client:
            await self._client.aclose()
