"""Per-request ID generation and propagation (FND-04).

Every response — success and error — carries an `X-Request-Id` header:
the inbound value when the client supplied one (correlation pass-through),
otherwise a freshly generated opaque ID. Exception handlers read the same
value via `get_request_id` so the structured error envelope's
`error.request_id` field always matches the response header exactly.

The header name is an implementation choice, not a documented contract
field (`docs/api-specification.md`'s fixed contract is the JSON body's
`request_id` field; the header is additional correlation convenience).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_ID_HEADER = "X-Request-Id"
_STATE_KEY = "request_id"


def get_request_id(request: Request) -> str:
    """Return the current request's ID, assigned by `RequestIdMiddleware`.

    Falls back to generating one if the middleware did not run (e.g. a
    handler invoked outside a real request context in a test) so callers
    never observe a missing/empty value.
    """
    value = getattr(request.state, _STATE_KEY, None)
    if isinstance(value, str) and value:
        return value
    return str(uuid.uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates the per-request correlation ID."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        inbound = request.headers.get(REQUEST_ID_HEADER)
        request_id = inbound.strip() if inbound and inbound.strip() else str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
