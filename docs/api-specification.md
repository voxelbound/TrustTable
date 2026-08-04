# TrustTable API Specification

## 1. Scope

This document defines the version 1 HTTP API contract at a resource and behavior level.

FastAPI and Pydantic remain the source of the generated OpenAPI schema.

Base path:

```text
/api/v1
```

Content type:

```text
application/json
```

Uploads use multipart form data.

## 2. Conventions

### Identifiers

Identifiers are opaque strings. Clients must not parse meaning from them.

### Timestamps

ISO 8601 UTC strings.

### Pagination

List endpoints use:

- `page`
- `page_size`
- `total_items`
- `total_pages`

Default page size: 50. Maximum: 200.

### Error format

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

### Idempotency

- GET and DELETE are idempotent.
- Review updates use PUT or PATCH with version checks.
- Upload is not automatically retried by the frontend.
- Finalization and retry endpoints must reject invalid lifecycle transitions.
- Rule test endpoints may be repeated safely.

### Concurrency

Mutable resources expose a version or updated timestamp. Conflicting writes return `409 CONFLICT`.

## 3. Operational endpoints

### GET `/health/live`

Confirms that the process is running.

### GET `/health/ready`

Confirms:

- configuration is valid
- storage is writable
- migrations are current
- worker service is ready

Ollama availability does not make the application unready when AI is optional.

### GET `/version`

Returns:

- application version
- API version
- schema version
- detector catalogue version
- build commit
- environment mode

## 4. AI status

### GET `/ai/status`

Returns:

- provider
- enabled state
- base location classification: local, remote, disabled
- configured model
- availability
- sample-value transmission state
- privacy summary
- safe error when unavailable

## 5. Demo dataset

### POST `/demo/sales`

Creates an analysis using the bundled synthetic sales dataset.

Optional request fields:

- seed
- row count
- issue profile

The hidden ground-truth manifest is never returned by normal product endpoints.

Response:

- `202 Accepted`
- analysis resource
- status URL

## 6. Analyses

### POST `/analyses`

Multipart fields:

- file
- optional worksheet
- optional user description
- optional analysis settings

Behavior:

1. validate request and upload limits
2. sanitize filename
3. store immutable source file
4. create queued analysis
5. return immediately

Response:

- `202 Accepted`
- analysis ID
- initial state
- status URL

### GET `/analyses/{analysis_id}`

Returns:

- metadata
- state
- stage
- progress
- dataset summary
- AI status
- timestamps
- failure details when safe
- available actions

### GET `/analyses/{analysis_id}/status`

Lightweight polling endpoint.

Returns:

- state
- stage
- progress percentage when meaningful
- current message
- poll interval recommendation
- cancellable state
- retryable state

### POST `/analyses/{analysis_id}/cancel`

Cancels a queued or active analysis.

Returns:

- updated state

### POST `/analyses/{analysis_id}/retry`

Creates or starts a linked retry according to implementation policy.

Returns:

- `202 Accepted`
- new attempt ID or updated attempt resource

### DELETE `/analyses/{analysis_id}`

Deletes:

- source file
- profile
- context
- findings
- evidence
- rules
- reports
- persistence records

Returns:

- `204 No Content`

Deletion of an active analysis first requests cancellation.

## 7. Worksheet discovery

### POST `/datasets/inspect`

Optional pre-analysis endpoint for Excel selection.

Returns:

- sanitized filename
- format
- worksheet names
- approximate shape where safe
- warnings
- limit violations

It must not execute formulas or macros.

## 8. Profile

### GET `/analyses/{analysis_id}/profile`

Returns versioned dataset and column profiles.

Query options:

- include technical metrics
- page/page size for columns
- column filter

Large representative-value payloads are excluded by default.

## 9. Context

### GET `/analyses/{analysis_id}/context`

Returns:

- current context
- confidence
- provenance
- confirmation state
- supporting evidence references

### PUT `/analyses/{analysis_id}/context`

Replaces editable context fields with validated user-confirmed values.

Requires resource version.

### GET `/analyses/{analysis_id}/questions`

Returns active guided questions.

### POST `/analyses/{analysis_id}/questions/{question_id}/answer`

Stores an answer and resulting context updates.

### POST `/analyses/{analysis_id}/finalize`

Valid when context is sufficiently confirmed or explicitly left unknown.

Triggers context-dependent analysis and optional AI interpretation.

Returns:

- `202 Accepted`
- updated status resource

## 10. Findings

### GET `/analyses/{analysis_id}/findings`

Filters:

- severity
- category
- review state
- detector ID
- column
- text search
- sort
- page
- page size

Response item includes:

- ID
- title
- severity
- confidence
- priority
- provenance summary
- affected counts
- category
- review state

### GET `/analyses/{analysis_id}/findings/{finding_id}`

Returns:

- deterministic observation
- evidence
- possible business impact
- remediation
- proposed rules
- review
- technical metadata
- security exposure information when applicable

### PATCH `/analyses/{analysis_id}/findings/{finding_id}/review`

Request:

- review state
- note
- optional dismissal reason
- expected version

Response:

- updated review

### GET `/analyses/{analysis_id}/findings/{finding_id}/evidence`

Returns bounded evidence details.

Sensitive and suspicious values are escaped, truncated, and permissioned by product rules.

## 11. Validation rules

### GET `/analyses/{analysis_id}/rules`

Returns proposed and confirmed rules.

### POST `/analyses/{analysis_id}/rules`

Creates a supported rule manually or from a confirmed proposal.

### PUT `/analyses/{analysis_id}/rules/{rule_id}`

Updates supported parameters.

### DELETE `/analyses/{analysis_id}/rules/{rule_id}`

Deletes a rule proposal or confirmed rule.

### POST `/analyses/{analysis_id}/rules/{rule_id}/test`

Executes the rule against the immutable dataset.

Returns:

- pass count
- fail count
- skipped count
- bounded failure examples
- execution duration

## 12. Reports and exports

### POST `/analyses/{analysis_id}/reports`

Generates an immutable report snapshot.

Request options:

- include dismissed findings
- include technical appendix
- include bounded examples

### GET `/analyses/{analysis_id}/reports`

Lists generated reports.

### GET `/analyses/{analysis_id}/reports/{report_id}`

Returns report metadata.

### GET `/analyses/{analysis_id}/reports/{report_id}/download`

Downloads Markdown.

### GET `/analyses/{analysis_id}/exports/rules.json`

Downloads validated rules.

### GET `/analyses/{analysis_id}/exports/rules.yaml`

Downloads validated rules.

## 13. Security exposure fields

Prompt-injection findings expose:

- `sent_to_model`
- `model_location`
- `sample_transmission_enabled`
- `protections_applied`
- `model_output_rejected`
- `display_sample`
- `full_value_available` according to safe product behavior

Raw suspicious text is never present in list endpoints.

## 14. Common error codes

- INVALID_REQUEST
- UNSUPPORTED_FILE_TYPE
- FILE_TOO_LARGE
- WORKBOOK_EXPANSION_LIMIT
- CELL_LIMIT_EXCEEDED
- MALFORMED_FILE
- MACRO_ENABLED_FILE
- WORKSHEET_REQUIRED
- ANALYSIS_NOT_FOUND
- INVALID_ANALYSIS_STATE
- ANALYSIS_FAILED
- ANALYSIS_NOT_CANCELLABLE
- ANALYSIS_NOT_RETRYABLE
- CONTEXT_VERSION_CONFLICT
- INVALID_CONTEXT
- FINDING_NOT_FOUND
- RULE_NOT_FOUND
- RULE_INVALID
- RULE_EXECUTION_FAILED
- MODEL_UNAVAILABLE
- MODEL_OUTPUT_INVALID
- STORAGE_UNAVAILABLE
- MIGRATION_REQUIRED
- CONFLICT
- INTERNAL_ERROR

## 15. API security requirements

- no raw stack traces
- no user-controlled filesystem paths
- unguessable IDs
- strict request limits
- safe content disposition filenames
- escaped display fields
- OpenAPI drift checked in CI
- delete semantics tested
- all mutation lifecycle transitions tested
