/**
 * Recognizes the backend's structured error envelope (`FND-04`,
 * `backend/src/trusttable_backend/schemas/errors.py`):
 *
 * ```json
 * { "error": { "code": "...", "message": "...", "details": {}, "request_id": "..." } }
 * ```
 *
 * Hand-written, not generated: the `@hey-api/openapi-ts` output under
 * `frontend/src/api/` only types the `422` validation-error response for
 * `api/v1/analyses.py`'s routes (FastAPI does not declare per-route
 * `responses={}` for the `404`/`409` structured errors those handlers
 * actually raise), so there is no generated type for this shape (`UI-01`,
 * `WP-025`, current repository evidence). This module recognizes the
 * envelope defensively at runtime instead of trusting a generated type
 * that does not exist for these error codes.
 */

export interface ApiErrorDetail {
  code: string
  message: string
  details: Record<string, unknown>
  request_id: string
}

export interface ApiErrorEnvelope {
  error: ApiErrorDetail
}

/** A safe, generic fallback shown when the response body does not match
 * the structured error envelope (network failure, an HTML error page,
 * an unexpected shape, etc.) — never derived from raw response text, so
 * no unvalidated server content reaches the UI through this path
 * (`docs/ui-specification.md` §8 "Rendering security"). */
export const FALLBACK_ERROR_MESSAGE =
  'Something went wrong while contacting the server. Please try again.'

export function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== 'object' || value === null) {
    return false
  }
  const error = (value as Record<string, unknown>).error
  if (typeof error !== 'object' || error === null) {
    return false
  }
  const detail = error as Record<string, unknown>
  return (
    typeof detail.code === 'string' &&
    typeof detail.message === 'string' &&
    typeof detail.request_id === 'string'
  )
}

/** The safe, display-ready message for an unknown API error body. Never
 * throws — a non-conforming body (or `undefined`) falls back to
 * {@link FALLBACK_ERROR_MESSAGE} rather than surfacing raw response
 * content. */
export function getApiErrorMessage(body: unknown): string {
  if (isApiErrorEnvelope(body)) {
    return body.error.message
  }
  return FALLBACK_ERROR_MESSAGE
}

/** The structured error code (e.g. `ANALYSIS_NOT_FOUND`) when the body
 * conforms to the envelope, otherwise `null`. */
export function getApiErrorCode(body: unknown): string | null {
  if (isApiErrorEnvelope(body)) {
    return body.error.code
  }
  return null
}
