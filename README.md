# epay

Official [ePay Business API](https://api.e-pay.et) client for Python.

Accept payments from every major Ethiopian mobile wallet and bank with one integration.

- **Sync and async clients** from one install, sharing one retry policy
- **Fully typed**, with `py.typed` and `TypedDict` response shapes
- **Automatic retries** with exponential backoff and jitter on `429`/`5xx`/network errors
- **Safe retries on initialize** — every attempt reuses one idempotency key
- **Constant-time webhook verification**, with helpers for Flask, Django, and FastAPI
- **`Decimal`-safe amounts**, so money never rides on a binary float
- One dependency: `httpx`

## Install

```sh
pip install epay
```

Requires Python 3.9 or newer.

## Quick start

```python
from epay import Epay

epay = Epay()  # reads EPAY_SECRET_KEY

session = epay.payments.initialize(
    amount="250.00",
    currency_code="ETB",
    customer_phone="+251911234567",
    merchant_reference="order_123",
    return_url="https://yourstore.com/orders/123/complete",
)

# Save session["reference"], then send the customer to pay.
redirect(session["checkoutUrl"])
```

The key prefix picks the environment: `sk_test_…` runs against the sandbox and
`sk_live_…` moves real money. There is no separate mode to configure.

Responses are plain dicts, typed as `TypedDict`. A field the API adds later is
readable immediately, without an SDK upgrade.

## Async

```python
from epay import AsyncEpay

async with AsyncEpay() as epay:
    session = await epay.payments.initialize(
        amount="250.00",
        currency_code="ETB",
        customer_phone="+251911234567",
    )
```

Both clients hold an HTTP connection pool, so close them — via a context
manager, `close()`, or `await aclose()`.

## Configuration

| Argument | Environment variable | Default |
| --- | --- | --- |
| `api_key` | `EPAY_SECRET_KEY` | *required* |
| `webhook_secret` | `EPAY_WEBHOOK_SECRET` | — |
| `base_url` | `EPAY_BASE_URL` | `https://api.e-pay.et/v1` |
| `timeout` | — | `30.0` seconds per attempt |
| `max_retries` | — | `2` |
| `default_headers` | — | `{}` |
| `http_client` | — | a new `httpx.Client` |

```python
epay = Epay(timeout=10.0, max_retries=3)

epay.mode  # 'live' | 'sandbox' | None
epay.is_sandbox  # bool
```

`repr(epay)` masks the key, so a client is safe to log.

### Bring your own httpx client

Pass `http_client` to share a pool, route through a proxy, or use mTLS. The SDK
never closes a client it did not create.

```python
import httpx
from epay import Epay

http_client = httpx.Client(
    proxy="http://proxy.internal:8080",
    limits=httpx.Limits(max_connections=20),
)
epay = Epay(http_client=http_client)
```

## Payments

### Initialize

```python
session = epay.payments.initialize(
    amount=Decimal("250.00"),  # str, int, Decimal, or float
    currency_code="etb",  # uppercased
    customer_phone="0911234567",  # rewritten to '+251911234567'
    merchant_reference="order_123",
    email="abebe@example.com",
    callback_url="https://yourstore.com/webhooks/epay",  # overrides the dashboard URL
    idempotency_key="order_123",
)
```

`amount`, `currency_code`, and `customer_phone` are validated locally, so a typo
raises `EpayValidationError` immediately instead of costing a round trip.

**On amounts.** Pass `str` or `Decimal`. A `float` is accepted and rounded
half-up to two places, but binary floats cannot represent every decimal amount
exactly, so money is better kept out of them. The result always carries two
decimal places.

**On idempotency keys.** If you omit `idempotency_key`, the SDK generates a
fresh one per call. That makes its internal retries safe — a retried
`initialize` cannot double-charge — but it does *not* deduplicate across
separate calls. Pass your own order id to get that guarantee.

### Verify before fulfilling

```python
receipt = epay.payments.verify(reference)
# receipt["status"] == "completed", plus serviceFee, paymentMethod, customer
```

The API rejects a transaction that is not yet `completed`, so use
`transactions.retrieve` first if you would rather branch on status than catch an
`EpayBadRequestError`.

### Cancel

```python
epay.payments.cancel(reference)  # returns None on 204
```

Only `pending` and `processing` transactions can be cancelled, and cancellation
is irreversible. This call is never retried automatically, because the endpoint
takes no idempotency key.

## Transactions

```python
transaction = epay.transactions.retrieve(reference)
timeline = epay.transactions.timeline(reference)

for event in timeline["events"]:
    print(event["eventType"], event["occurredAt"], event["errorCode"])
```

### Listing and pagination

The endpoint is cursor-paginated at a fixed 10 per page. Iterate a page to walk
every following page, fetching lazily and carrying your filters along:

```python
from datetime import date

for transaction in epay.transactions.list(
    status="completed",
    currency="ETB",
    from_date=date(2026, 8, 1),
    to_date=date(2026, 8, 31),
):
    print(transaction["reference"], transaction["amount"])
```

`from_date` and `to_date` accept a `date`, `datetime`, or ISO string, and the
API caps the range at 90 days.

Other ways to consume the same endpoint:

```python
page = epay.transactions.list()
page.data  # exactly this page, no extra requests
page.has_more  # bool
page.next_page()  # the next TransactionPage, or None

recent = epay.transactions.list().to_list(limit=50)  # cap the walk

for page in epay.transactions.list().pages():  # page at a time
    process_batch(page.data)
```

The async client mirrors this with `async for` and `await page.to_list()`:

```python
async for transaction in await epay.transactions.list(status="failed"):
    ...
```

## Payment providers

```python
epay.payment_providers.list()  # compact, for dropdowns
epay.payment_providers.get_all()  # with category and isEnabled
epay.payment_providers.list_enabled()  # only what you can route to today
```

Both endpoints are mode-aware and permission-gated: `list` needs
`list_platform_payment_provider`, `get_all` needs
`get_platform_payment_provider`.

## Webhooks

Verify the `X-Epay-Signature` header against the **raw** request body before you
trust a payload. Re-serializing parsed JSON can reorder keys and change the
digest, which rejects valid deliveries.

### Flask

```python
import os
from flask import Flask, request, abort
from epay import EpayWebhookSignatureError
from epay.integrations.flask import construct_event_from_request

app = Flask(__name__)


@app.post("/webhooks/epay")
def epay_webhook():
    try:
        event = construct_event_from_request(request, os.environ["EPAY_WEBHOOK_SECRET"])
    except EpayWebhookSignatureError as error:
        abort(401, str(error))

    queue.enqueue(event)  # acknowledge fast, process later
    return "", 200
```

### FastAPI

```python
from fastapi import FastAPI, HTTPException, Request
from epay import EpayWebhookSignatureError
from epay.integrations.asgi import construct_event_from_request

app = FastAPI()


@app.post("/webhooks/epay", status_code=200)
async def epay_webhook(request: Request):
    try:
        event = await construct_event_from_request(request, settings.epay_webhook_secret)
    except EpayWebhookSignatureError as error:
        raise HTTPException(status_code=401, detail=str(error))

    await queue.enqueue(event)
    return {"received": True}
```

Take the whole `Request`, not a parsed Pydantic model — FastAPI would hand you
re-serialized JSON, whose digest no longer matches.

### Django

```python
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from epay import EpayWebhookSignatureError
from epay.integrations.django import construct_event_from_request


@csrf_exempt  # ePay is a third party and sends no CSRF token
def epay_webhook(request):
    try:
        event = construct_event_from_request(request, settings.EPAY_WEBHOOK_SECRET)
    except EpayWebhookSignatureError as error:
        return HttpResponseForbidden(str(error))

    enqueue(event)
    return HttpResponse(status=200)
```

### Verifying by hand

```python
from epay import construct_webhook_event

event = construct_webhook_event(raw_body, signature_header, secret)
```

It fails closed: any event it returns had a valid signature.

### Handling events

```python
if event["event"] == "payment.success":
    fulfil(event["reference"])
elif event["event"] in ("payment.failed", "payment.cancelled"):
    release(event["reference"])
elif event["event"] in ("payment.refunding", "payment.refunded", "payment.reversed"):
    reconcile(event)
```

ePay retries anything that is not a `2xx` within 10 seconds, up to 5 attempts,
so keep the handler fast and make it idempotent — deduplicate on
`event["reference"]`.

## Error handling

Every failure is an `EpayError`. HTTP failures carry the status, parsed body, and
response headers.

```python
from epay import (
    EpayAPIError,
    EpayBadRequestError,
    EpayNotFoundError,
    EpayRateLimitError,
)

try:
    receipt = epay.payments.verify(reference)
except EpayNotFoundError:
    return None
except EpayBadRequestError:
    return "not settled yet"
except EpayRateLimitError as error:
    time.sleep(error.retry_after_seconds or 1)
    raise
except EpayAPIError as error:
    logger.error("ePay %s on %s: %s", error.status, error.request, error.body)
    raise
```

| Class | Raised when |
| --- | --- |
| `EpayValidationError` | A value failed local validation; no request was sent |
| `EpayConfigError` | The client was constructed with unusable options |
| `EpayBadRequestError` | `400` |
| `EpayAuthenticationError` | `401` — key missing, invalid, or revoked |
| `EpayPermissionDeniedError` | `403` — IP not whitelisted, or key lacks a permission |
| `EpayNotFoundError` | `404` |
| `EpayConflictError` | `409` |
| `EpayRateLimitError` | `429` — exposes `retry_after_seconds` |
| `EpayServerError` | `5xx` |
| `EpayTimeoutError` | The attempt exceeded `timeout` |
| `EpayConnectionError` | No response was received at all |
| `EpayWebhookSignatureError` | A webhook signature was missing or wrong |

`EpayValidationError` also subclasses `ValueError`, so existing handlers keep
working. `429`, `5xx`, and network errors are retried automatically before
surfacing.

## Sandbox testing

Use a `sk_test_…` key with the documented magic phone numbers:

| Phone | OTP | Outcome |
| --- | --- | --- |
| `251900000000` | `000111` | Generic sandbox account |
| `251900000001` | `123456` | Completes, fires `payment.success` |
| `251900000002` | `654321` | `INVALID_OTP` |
| `251900000003` | `111111` | `OTP_EXPIRED` |
| `251900000004` | — | Declined, fires `payment.failed` |

Generate a fresh idempotency key per test run: reusing one returns the cached
response instead of triggering the scenario again.

### Testing your own code

Inject an `httpx.MockTransport` and no request leaves the process:

```python
import httpx
from epay import Epay


def handler(request):
    return httpx.Response(200, json={"reference": "PAB1", "checkoutUrl": "…"})


epay = Epay("sk_test_fake", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
```

## Unmodelled endpoints

`epay.request` reaches anything this version does not wrap yet, with the same
auth, timeout, retry, and error handling:

```python
data = epay.request("GET", "/some/new/endpoint", params={"limit": 10})
```

## Development

```sh
pip install -e ".[dev]"
pytest         # 162 tests, no network
mypy           # strict
ruff check .
ruff format .
```

## Releasing

CI runs the suite on Python 3.9 through 3.13, mypy strict and ruff on 3.12, and
a packaging job that builds both artifacts, runs `twine check --strict`, and
installs the wheel into a clean venv to confirm it imports.

One-time setup — **no API token needed**, this uses Trusted Publishing:

1. At pypi.org → Account → Publishing, add a **pending publisher**:
   - PyPI project name: `epay`
   - Owner: `epay-et`, repository: `python-sdk`
   - Workflow: `release.yml`, environment: `pypi`
2. Repeat at test.pypi.org with environment `testpypi`.
3. Create GitHub environments named `pypi` and `testpypi`.

To release:

```sh
# Bump `version` in pyproject.toml and src/epay/_version.py, then:
git commit -am "release: v0.2.0"
git tag v0.2.0 && git push --follow-tags
```

The tag triggers `release.yml`, which verifies the tag matches
`pyproject.toml`, builds, validates metadata, and publishes to PyPI via OIDC.

To rehearse, run the workflow manually and pick `testpypi`.

PyPI never lets a filename be reused, so a bad upload cannot be replaced — only
yanked and superseded. The tag/version check exists to prevent that.

## License

MIT
