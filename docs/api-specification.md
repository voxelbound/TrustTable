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

AI provider (`llama.cpp`) availability does not make the application unready when AI is optional.

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

**Clarified (`docs/decision-log.md` D-037, `v0.2`):** "finalize" ends
the context-confirmation sub-flow and makes confirmed context
**available to** enrichment — it does not itself perform a synchronous
enrichment call. This is additive: it never re-runs or gates
deterministic detection, and it never changes the underlying
analysis's own state (which is already `completed` before finalize can
be called — see `docs/architecture.md` §6's two-phase model). A future
pre-analysis-gating architecture, where finalize instead triggers
detection itself, remains possible but is not what `v0.2` implements.

**Corrected (`WP-065`, defect fix):** every route in this section is
now implemented (`API-02`/`UI-02`, `WP-059`/`WP-064`) — this section
previously and incorrectly stated otherwise after implementation
shipped. `finalize`'s own enrichment capability is the already-shipped,
on-demand `GET .../findings/{finding_id}/explanation` route (§10),
which reads confirmed context only after `context_finalized` is set —
not a forced side effect of `finalize` itself (`docs/decision-log.md`
D-037's appended `WP-064` r2 closure note).

Returns:

- `202 Accepted`
- updated resource (the enrichment result, layered over the unchanged,
  already-`completed` deterministic analysis)

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

### GET `/analyses/{analysis_id}/findings/{finding_id}/row-context`

Request (query parameters):

- `anchor_row` (required) — identifies the RowReference (the same
  RowReference identity already used for this finding's affected row
  references) to center the window on. `anchor_row` is not a second,
  independently defined numbering; it is the RowReference's stable
  internal row number. The value must equal the row number of one of
  this finding's own affected row references, or the request is
  rejected (404 `ROW_NOT_IN_FINDING`).
- `before`, `after` (optional integers, `>= 0`, default 3 each) —
  requested window size. **Resolved (`FIND-01`, `WP-038`):** the server
  enforces a maximum of 25 rows per side (`max_window`); an over-limit
  request is clamped, not rejected, as is a request that would extend
  past the start or end of the file. The response distinguishes
  requested from actual window size in every case (below).

Returns:

- resolved window: `requested_before`, `requested_after`,
  `actual_before`, `actual_after`, `truncated_at_start`,
  `truncated_at_end`, current `max_window`
- column list (original names, in source order)
- one entry per row in the window: its RowReference, `is_anchor`,
  `is_affected_by_finding` (true for the anchor and any other of this
  finding's own affected rows inside the window), and values by column
- values are returned as retained; any truncation for display is a
  client rendering behavior, not a function this endpoint performs

Capability boundary: `anchor_row` must resolve to a RowReference
already belonging to the finding's own affected row references — this
endpoint reads context around a finding, not arbitrary rows in the file.

### GET `/analyses/{analysis_id}/findings/{finding_id}/explanation`

Added (`AI-05`/`UI-02` slice 1, `WP-063`; documented retroactively by
`WP-065`, a defect fix that also corrected two stale "not yet
implemented"/"no route calls a provider" claims elsewhere in this repo
after this route and §9's Context routes had already shipped).

Always computes and, by default (`llm_provider="disabled"`), returns a
deterministic explanation of the finding — no AI call, first
implementation of `docs/product-requirements.md` §5.7's
"deterministic explanations" AI-disabled-mode requirement. When a real
AI provider is configured, additionally attempts a validated,
evidence-grounded explanation through it; on acceptance the AI
explanation is returned instead, on rejection or provider error the
deterministic explanation is returned unchanged (graceful
degradation). When the analysis's context has been finalized
(`POST .../finalize`), the confirmed context is also made available to
this call, grounding the explanation further.

Returns:

- `narrative` — one or two sentences explaining the finding
- `provenance` — `"deterministic_fallback"` or `"ai_interpretation"`
- `provider_name`, `model_identifier` — both `null` unless `provenance`
  is `"ai_interpretation"`
- `ai_call_status` (`WP-065`) — exactly one of `"not_configured"`
  (no AI provider configured, no attempt made), `"attempted_accepted"`,
  `"attempted_rejected"` (a provider was called but its output, and any
  bounded retries, never validated), `"attempted_provider_error"` (a
  provider was called and failed to respond). Deliberately independent
  of `provenance` alone, which cannot distinguish "never attempted"
  from "attempted and failed", and deliberately independent of a
  finding's own `security_exposure` (§13) — see D-038.
- `evidence_sent_to_model`, `confirmed_context_sent_to_model` (`WP-065`
  r4) — booleans disclosing D-038's axis 5 (finding/evidence/context
  metadata exposure) for this specific request, independent of
  `ai_call_status` (axes 1-3) and `security_exposure` (axis 4, raw
  dataset-sample exposure — never reflected here). Both `False` when
  `ai_call_status == "not_configured"`; `evidence_sent_to_model` is
  `True` on every attempted call (this finding's own bounded `Evidence`
  is always sent); `confirmed_context_sent_to_model` is additionally
  `True` only once `POST .../finalize` has been called for this
  analysis.
- `referenced_evidence_ids`, `referenced_columns` — grounding proof,
  always derived from what was actually sent, never the model's own
  claims

Raises `ANALYSIS_NOT_FOUND`/`FINDING_NOT_FOUND` per the sibling finding
routes.

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

**Scope boundary (`WP-065`, defect fix; D-038):** these fields describe
only whether *this finding's own flagged raw dataset value* would be
sent to a model by the deterministic detection pipeline — always
`False`/not-sent today. They are independent of, and must never be
read as, a general "was AI used" indicator: §10's
`GET .../findings/{finding_id}/explanation` route can independently
call a real configured provider for the same finding (using only
bounded evidence, never this flagged raw value) and discloses that
call's own status via its own `ai_call_status` field.

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
- ROW_NOT_IN_FINDING
- QUESTION_NOT_FOUND
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
