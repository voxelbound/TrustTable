"""Request-body size limits, enforced by the backend as the single authority
(`UX-02`, D-068, `docs/api-specification.md` §15).

The frontend proxy applies no separate size limit, so every request body is
counted here as it streams, before it is buffered in full:

- the two upload routes (`POST /api/v1/analyses` and `POST
  /api/v1/staged-uploads`) allow `MAX_FILE_SIZE_MB` plus 1 MiB of multipart
  overhead and answer `413 FILE_TOO_LARGE`;
- every other request body is limited to 1 MiB and answers
  `413 REQUEST_TOO_LARGE`.

When a body exceeds its limit (or declares a `Content-Length` that already does)
the middleware stops feeding the application: it reports a client disconnect so
body parsing halts, discards anything the application then tries to send, and
answers the request itself with the shared error envelope. It does not raise
from inside the request, because FastAPI and Starlette turn exceptions raised
while reading a body into a generic `400`. Requests that never read a body are
unaffected.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any, Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Allowance for multipart framing around a file at the size limit.
MULTIPART_OVERHEAD_BYTES: Final[int] = 1024 * 1024
#: The limit for every request body that is not an upload.
DEFAULT_BODY_LIMIT_BYTES: Final[int] = 1024 * 1024

UPLOAD_PATHS: Final[frozenset[str]] = frozenset({"/api/v1/analyses", "/api/v1/staged-uploads"})
_BODY_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_REQUEST_ID_KEY: Final[str] = "request_id"


def _refusal_body(upload: bool, max_file_bytes: int, request_id: str) -> dict[str, Any]:
    if upload:
        code = "FILE_TOO_LARGE"
        message = "The uploaded file exceeds the maximum allowed size."
        max_bytes = max_file_bytes
    else:
        code = "REQUEST_TOO_LARGE"
        message = "The request body is too large."
        max_bytes = DEFAULT_BODY_LIMIT_BYTES
    return {
        "error": {
            "code": code,
            "message": message,
            "details": {"max_bytes": max_bytes},
            "request_id": request_id,
        }
    }


class RequestBodyLimitMiddleware:
    """Pure ASGI middleware: count request body bytes as they are read."""

    def __init__(self, app: ASGIApp, *, max_file_bytes: Callable[[], int]) -> None:
        self._app = app
        self._max_file_bytes = max_file_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _BODY_METHODS:
            await self._app(scope, receive, send)
            return

        upload = scope["method"] == "POST" and scope["path"] in UPLOAD_PATHS
        max_file_bytes = self._max_file_bytes()
        limit = max_file_bytes + MULTIPART_OVERHEAD_BYTES if upload else DEFAULT_BODY_LIMIT_BYTES

        declared = _declared_length(scope)
        seen = 0
        checked_declared = False
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal seen, checked_declared, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            if not checked_declared:
                checked_declared = True
                if declared is not None and declared > limit:
                    exceeded = True
                    return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if exceeded:
                return  # the application saw a disconnect; the answer is ours
            await send(message)

        try:
            await self._app(scope, limited_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded:
            await self._refuse(scope, send, upload, max_file_bytes)

    @staticmethod
    async def _refuse(scope: Scope, send: Send, upload: bool, max_file_bytes: int) -> None:
        state = scope.get("state") or {}
        request_id = state.get(_REQUEST_ID_KEY) if isinstance(state, dict) else None
        body = json.dumps(
            _refusal_body(upload, max_file_bytes, str(request_id or uuid.uuid4()))
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
