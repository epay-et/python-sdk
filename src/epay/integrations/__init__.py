"""Framework webhook helpers.

Each module here is duck-typed against its framework's request object, so
importing one does not require the framework to be installed and none of them
pull in a dependency of their own.

- :mod:`epay.integrations.flask` -- Flask and Quart
- :mod:`epay.integrations.django` -- Django
- :mod:`epay.integrations.asgi` -- FastAPI, Starlette, and Litestar

All of them ultimately call :func:`epay.webhooks.construct_webhook_event`, which
fails closed: any event they return had a valid signature.
"""

from __future__ import annotations

from typing import List

__all__: List[str] = []
