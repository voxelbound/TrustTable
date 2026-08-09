"""Application-level structured error exception (FND-04).

Any route may raise `AppError` to produce a deliberate, structured business
error instead of an ad-hoc `HTTPException`. No call site exists yet for
most `docs/api-specification.md` §14 codes because the resources they name
(analyses, findings, rules, ...) are not implemented — future backlog items
raise `AppError` with their own appropriate `code`/`status_code` at their
own call sites.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """A deliberate, structured API error.

    Args:
        code: A short machine-readable error code. Conventionally one of
            `trusttable_backend.schemas.errors.KNOWN_ERROR_CODES`, but not
            enforced as a closed set (see that module's docstring).
        message: A safe, human-readable message. Must never contain raw
            exception text, stack traces, secrets, or unvalidated
            dataset-derived content.
        status_code: The HTTP status code to return.
        details: Optional bounded structured detail. Must be safe to
            serialize directly into the response body.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
