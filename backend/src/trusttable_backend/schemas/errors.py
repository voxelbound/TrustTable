"""Pydantic schemas for the structured API error envelope (FND-04).

The shape here is pinned exactly to `docs/api-specification.md`'s
documented "Error format" — this module does not define the contract, it
mirrors an already-fixed one:

```json
{
  "error": {
    "code": "ANALYSIS_NOT_FOUND",
    "message": "The requested analysis was not found.",
    "details": {},
    "request_id": "..."
  }
}
```
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

#: Reference list mirroring `docs/api-specification.md` §14 "Common error
#: codes". This is documentation/regression-test aid, not a runtime-enforced
#: closed set: most of these name resources (analyses, findings, rules)
#: that do not exist yet, and a future backlog item may need to add a code
#: here before the doc is next revised. Keep in sync with §14.
KNOWN_ERROR_CODES: tuple[str, ...] = (
    "INVALID_REQUEST",
    "UNSUPPORTED_FILE_TYPE",
    "FILE_TOO_LARGE",
    "WORKBOOK_EXPANSION_LIMIT",
    "CELL_LIMIT_EXCEEDED",
    "MALFORMED_FILE",
    "MACRO_ENABLED_FILE",
    "WORKSHEET_REQUIRED",
    "ANALYSIS_NOT_FOUND",
    "INVALID_ANALYSIS_STATE",
    "ANALYSIS_FAILED",
    "ANALYSIS_NOT_CANCELLABLE",
    "ANALYSIS_NOT_RETRYABLE",
    "CONTEXT_VERSION_CONFLICT",
    "INVALID_CONTEXT",
    "FINDING_NOT_FOUND",
    "RULE_NOT_FOUND",
    "RULE_INVALID",
    "RULE_EXECUTION_FAILED",
    "MODEL_UNAVAILABLE",
    "MODEL_OUTPUT_INVALID",
    "STORAGE_UNAVAILABLE",
    "MIGRATION_REQUIRED",
    "CONFLICT",
    "INTERNAL_ERROR",
)


class ErrorDetail(BaseModel):
    """The `error` object nested inside every structured error response."""

    code: str
    message: str
    details: dict[str, Any] = {}
    request_id: str


class ErrorResponse(BaseModel):
    """Body for every structured API error response: `{"error": {...}}`."""

    error: ErrorDetail
