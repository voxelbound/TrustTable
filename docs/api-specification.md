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

**Implemented for `.csv` and `.xlsx` (`ING-03`).** `.xlsm` and any other
extension is `415 UNSUPPORTED_FILE_TYPE`. For `.xlsx` the optional
`worksheet` form field names the worksheet to analyze:

- a workbook with exactly one visible worksheet uses it when no
  `worksheet` is given; with several and no choice the request is
  `400 WORKSHEET_REQUIRED` and `error.details.worksheets` lists every
  worksheet name;
- a `worksheet` that does not exist is `400 INVALID_REQUEST` with the same
  `details.worksheets` list; a `worksheet` sent with a `.csv` is
  `400 INVALID_REQUEST`;
- the workbook is inspected before any analysis is created and refused with
  `415 MACRO_ENABLED_FILE` (macro content), `413 WORKBOOK_EXPANSION_LIMIT`
  (size, entry-count, worksheet-count or decompression limits) or
  `400 MALFORMED_FILE` (not a zip package, an OLE/encrypted file, unsafe
  entry names, DOCTYPE or entity declarations, or unreadable XML). The
  messages are fixed text; nothing from the workbook is echoed back except
  worksheet names for selection;
- row, column and cell limits (`CELL_LIMIT_EXCEEDED`) are enforced when the
  pipeline reads the chosen worksheet, so an over-limit worksheet ends as a
  `failed` analysis, as an over-limit CSV does.

The analysis's dataset summary carries `selected_worksheet` (the name read,
`null` for CSV). `POST /datasets/inspect` (§7) is not implemented yet.

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

Implemented (`JOB-01` slice 2): only a `FAILED` analysis is retryable
(`ANALYSIS_NOT_RETRYABLE` otherwise). Creates a new, independent analysis
over the original's own dataset content, linked via
`retry_source_analysis_id` — never a versioned attempt reusing the
original `analysis_id`. The original analysis is never mutated.

Returns:

- `202 Accepted`
- the new analysis resource (its own `analysis_id` is the "new attempt
  ID"), `status_url`, and `retry_source_analysis_id`

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

**Implemented (`DEL-01`, `D-048`):** the route is real. It removes the
analysis row (the uploaded content, profile, context, questions, findings,
evidence, rules, reviews and the AI enrichment record) and every stored
report in one transaction, and returns `204` with no body. It is permanent:
there is no soft delete or undo. A queued or running analysis is asked to
cancel and then deleted without waiting for its worker; the worker's later
writes cannot bring the analysis back. Afterwards every route for that
analysis, including the report routes and the rules export, is
`404 ANALYSIS_NOT_FOUND`, and so is a repeated `DELETE`. The database is
opened with SQLite `secure_delete` so the deleted bytes are overwritten and
not left readable in the database file. This does not reach copies a
filesystem or a backup keeps.

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

### Confirmed relationships (`DET-03`, `docs/decision-log.md` D-059, D-060)

A user-stated relationship between columns of one analysis, kept apart from the
context above. The first kind is `start_end_date`: one column holds a start date,
another an end date. It is never inferred. Nothing reads these records yet: no
check runs, and no detector, gate or observation depends on them.

#### POST `/analyses/{analysis_id}/confirmed-relationships`

Body (strict; unknown fields are rejected, every string is bounded, there is no
free-text field, and a column is named only by its internal key):

- `transition`: `confirm`, `replace` or `withdraw`
- `kind`: `start_end_date`
- `relationship_id` and `expected_version`: required for `replace` and `withdraw`,
  forbidden for `confirm`
- `start` and `end`: the two columns' internal keys; required for `confirm` and
  `replace`, forbidden for `withdraw`
- `source`: `direct` (default) or `suggestion`

Each success is a new immutable version. `201 Created` for a new relationship,
`200 OK` for a new version of an existing one. The response carries
`relationship_id`, `version`, `state` (`active` or `withdrawn`), `check_status` and
`recorded_at`. `check_status` is an open, additive set; clients treat an unknown
value as opaque and rely on it and the identifiers, not on the status code alone.
In this foundation it is always `not_active`: no check exists to run, and it never
means the data passed one.

Writes are version-aware: `expected_version` must equal the relationship's current
version, so an older client cannot overwrite a newer confirmation, and of two
concurrent writers holding the same version exactly one succeeds. Only a
`completed` analysis accepts a write, because the keys are checked against its
stored profile columns.

Refusals use stable codes and never echo a submitted value:

| Status | Code | Meaning |
|---|---|---|
| 404 | `ANALYSIS_NOT_FOUND`, `RELATIONSHIP_NOT_FOUND` | no such analysis or relationship |
| 409 | `INVALID_ANALYSIS_STATE` | the analysis is not `completed` |
| 409 | `RELATIONSHIP_VERSION_CONFLICT` | `expected_version` is not current; `details.current_version` says which is |
| 409 | `RELATIONSHIP_WITHDRAWN` | the relationship was withdrawn; withdrawal is final |
| 409 | `ACTIVE_RELATIONSHIP_LIMIT_REACHED` | 50 active relationships; withdrawn ones do not count |
| 409 | `RELATIONSHIP_VERSION_LIMIT_REACHED` | 50 versions of this relationship (blocks `replace`) |
| 409 | `ANALYSIS_RELATIONSHIP_VERSION_LIMIT_REACHED` | 500 versions in the analysis (blocks `confirm` and `replace`) |
| 422 | `INVALID_RELATIONSHIP_TRANSITION` | the fields do not fit the transition |
| 422 | `COLUMN_REFERENCE_NOT_IN_ANALYSIS` | a key is not a column of this analysis |
| 422 | `INVALID_REQUEST` | malformed body, unknown kind, transition or field, over-long value |

A withdrawal is exempt from both version caps, so a relationship at its cap can
always be withdrawn. A later confirmation of the same columns is a new
relationship with a new id. The same column on both sides, or a column in several
relationships, is stored and not rejected: whether it is meaningful is for a later
gate to judge.

#### GET `/analyses/{analysis_id}/confirmed-relationships`

Returns every relationship in the order it first appeared, each with its `state`,
`check_status`, `current` version and the full ordered `history` of versions.
Each version carries a server-assigned version number and `recorded_at`, and a
`source` that is the client's own assertion and is not verified; there is no
identity field. The access model is that of every other analysis route: the analysis id
is the only capability. The records end with the analysis (`DELETE
/analyses/{analysis_id}` removes them).

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

**Filters and pagination remain planned, not yet implemented** — a later
`UI-03`-adjacent addition; every finding is currently returned unfiltered
in detector order. `review_state`/`note`/`dismissal_reason`/`reviewed_at`
(`REV-01`, `WP-083`) are implemented, defaulting to
`"unreviewed"`/`null`/`null`/`null` for a finding with no recorded
review.

### GET `/analyses/{analysis_id}/findings/{finding_id}`

Returns:

- deterministic observation
- evidence
- possible business impact (`GET .../explanation`, a separate route)
- remediation (`GET .../explanation`, a separate route)
- proposed rules (`GET .../rule-proposal`, a separate route)
- review state (`REV-01`, `WP-083` — implemented on this response
  directly, not a separate route)
- technical metadata
- security exposure information when applicable

### PUT `/analyses/{analysis_id}/findings/{finding_id}/review`

**Implemented (`REV-01`, `WP-083`).** Sets (replacing any prior value)
one finding's review record and persists it immediately — a review has
no separate offer/execute step, unlike a rule proposal, so `PUT` (an
idempotent full replace) rather than the originally-sketched `PATCH`
with an `expected version`: TrustTable is a local-first, single-manager
tool (`docs/product-requirements.md` §1's "Primary user: Business
manager"), so there is no concurrent-editor conflict a version check
would guard against, unlike `context`'s own multi-step confirm/infer
collaborative race.

Request:

- `state` — one of `unreviewed`/`confirmed`/`dismissed`/
  `needs_investigation`
- `note` (optional)
- `dismissal_reason` — required and non-empty when `state` is
  `dismissed`, forbidden otherwise

Response: `finding_id`, `review_state`, `note`, `dismissal_reason`,
`reviewed_at` (server-assigned).

Raises `404 ANALYSIS_NOT_FOUND`, `409 INVALID_ANALYSIS_STATE` (not yet
`completed`), `404 FINDING_NOT_FOUND`, or `422 REVIEW_INVALID` (an
unrecognized `state`, or a `dismissal_reason` that violates the
required/forbidden rule above) — the same structured-error pattern as
`RULE_INVALID`.

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
(`POST .../finalize`), the context fields **the user confirmed or
corrected** are also made available to this call, grounding the analysis
further; inferred or unknown fields are never sent (`AI-08`, D-040).

**Four-section analysis (`AI-08`, D-040).** Despite its name (kept for
compatibility), this resource returns one finding's whole grounded
analysis: an explanation, possible business impact, remediation and a
proposed validation rule. When `provenance` is `"ai_interpretation"` all
four come from a single validated, structurally constrained AI response
(`finding_analysis_v1`); otherwise they come from TrustTable's
deterministic built-in guidance, so every section is populated with AI
disabled, rejected or failing. The AI-produced sections are advisory.

Returns:

- `narrative` — the explanation: one or two sentences explaining the
  finding
- `provenance` — `"deterministic_fallback"` or `"ai_interpretation"`
- `business_impact` — 1–3 *potential*-impact statements, each with
  `statement`, a `basis` (`"confirmed_context"` or `"assumption"`),
  `evidence_ids` (the evidence it relates to), `context_fields` and
  `assumption` (always present: the condition the statement depends on).
  `basis` is derived by TrustTable, never chosen by a model:
  `"confirmed_context"` means the statement cites context the user
  confirmed or corrected, so show it as *informed by* that context;
  `"assumption"` means it is only a conditional possibility. There is
  deliberately no `"evidence"` basis — the deterministic evidence
  establishes what was found in the data, not what it costs a business — so
  a client must never present any statement as evidence-backed or as a
  fact
- `remediation` — 1–3 structured recommendations (`REM-01`, `docs/domain-
  model.md` §16), each with `remediation_id`, `action_summary`,
  `responsible_role`, `urgency`, `historical_correction_guidance`
  (correcting rows already affected), `source_system_prevention_guidance`
  (preventing recurrence at the source), `risk_warning` (always
  populated — never `null`/empty), `verification_step`,
  `technical_example` (`null` when not applicable) and `evidence_ids`.
  Advisory only: TrustTable never changes uploaded data, and no field
  claims it did
- `validation_rule` — a proposed rule: `rule_type` (one of the §11 /
  `docs/product-requirements.md` §13 types), `columns`, `description`,
  and `status`, which is always `"proposed"`. It is not run, enforced or
  exported (the rule engine is a later item); a client must never
  present it as active
- `provider_name` — `null` unless `provenance` is `"ai_interpretation"`
- `model_identifier` — `null` unless `provenance` is
  `"ai_interpretation"`; then only a **sanitized** identifier (the final
  path segment of `LLM_MODEL`, bounded), never a filesystem path
- `ai_provenance` — `null` unless `provenance` is `"ai_interpretation"`;
  then human-readable labels (`deployment_label` "Local AI",
  `runtime_label` "llama.cpp", `model_label` "Qwen3.5 4B",
  `quantization` "Q4_K_M", `model_identifier`). This is what a UI shows;
  the raw configured model value never leaves the backend
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
  analysis **and** at least one context field was user-confirmed or
  corrected (so it is `False` when the user finalized without confirming
  anything).
- `referenced_evidence_ids`, `referenced_columns` — grounding proof,
  always derived from what was actually sent, never the model's own
  claims

Raises `ANALYSIS_NOT_FOUND`/`FINDING_NOT_FOUND` per the sibling finding
routes.

### GET `/analyses/{analysis_id}/observations` (`DET-03` closure package 2; provisional, read-only; `docs/decision-log.md` D-063)

Returns the neutral observations detectors stated about the analysis, separate
from findings. An observation is not a finding: it has no severity, confidence,
priority or review state, never affects the trust assessment, and is not part of any
AI payload, export or report.

```json
{
  "items": [
    {
      "observation_id": "structural.mixed_types.observation.amount",
      "kind": "value_evidence",
      "producer_detector_id": "structural.mixed_types",
      "summary": "Column 'amount' has 12 non-blank value(s) of more than one shape: 9 numeric-like, 3 text-like.",
      "affected_columns": [{"original_name": "amount", "internal_key": "amount", "ordinal": 1}],
      "affected_row_numbers": [4, 7, 9],
      "scope": "full"
    }
  ],
  "total_items": 1
}
```

`kind` is a closed vocabulary with one value, `value_evidence`; a later kind is
added and never changes this one. `affected_row_numbers` are at most 20 example row
numbers, never cell values. The detector's structured payload is not exposed,
matching finding evidence. An unknown analysis returns `404 ANALYSIS_NOT_FOUND`; a
known analysis that is not completed, or has none, returns an empty `items` list.
There is no write route. The response shape is provisional so that later dismissal,
suppression, history and further kinds can be added without a breaking change.

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

### GET `/analyses/{analysis_id}/findings/{finding_id}/rule-proposal`

Builds and executes (never persists) a deterministic candidate rule for
one finding.

**Implemented (`RULE-01`, complete):** `GET`/`POST`/`GET .../{rule_id}`/
`POST .../{rule_id}/test`/`DELETE .../{rule_id}` are real, for all 11
`docs/product-requirements.md` §13 rule types (`expression_comparison`/
`conditional_rule` added in slice 2, `WP-079`). `POST` executes
synchronously against the analysis's real current rows and returns the
created rule with its result in the same response — there is no separate
"proposed" state persisted by `POST` itself (every rule is executed and
stored immediately). `PUT` (parameter editing in place) is **not yet
implemented**: change a rule by deleting and recreating it. Request/
response shapes mirror `docs/domain-model.md` §18/§19 exactly (see
`domain.rules.ValidationRule`/`RuleExecutionResult`); an unknown
`column_names` entry is `422 UNKNOWN_RULE_COLUMN`, a malformed parameter
shape for `rule_type` is `422 INVALID_RULE_PARAMETERS`, an unknown
`rule_id` is `404 RULE_NOT_FOUND`, and a known analysis not yet
`COMPLETED` is `409 INVALID_ANALYSIS_STATE`.

**Implemented (`RULE-02` slice 1, `WP-080`):**
`GET .../findings/{finding_id}/rule-proposal` deterministically derives a
candidate rule for 9 of 13 detector ids (parameters read verbatim from
the finding's own `Evidence`, never a new calculation, never AI), builds
and executes it against the analysis's real current rows, and returns it
**unpersisted** — `{"available": bool, "reason": str | null, "rule":
ValidationRuleResponse | null, "result": RuleExecutionResultResponse |
null, "ai_call_status": str, "evidence_sent_to_model": bool}`.
`available: false` (never an error) with a stated `reason` means no safe
proposal exists for that detector. `POST .../rules` gained an optional
`source_finding_id`: when given, the finding must exist
(`404 FINDING_NOT_FOUND` otherwise) and the persisted rule records
`source_finding_ids` set, with `provenance` determined by that finding's
own detector (see below). Omitted (the default): unchanged
`provenance: "user_authored"`. Raises the same `ANALYSIS_NOT_FOUND`/
`INVALID_ANALYSIS_STATE`/`FINDING_NOT_FOUND` semantics as the sibling
finding routes.

**Implemented (`RULE-02` slice 2, `WP-081`):** for exactly one of the 4
slice-1-excluded categories,
`consistency.inconsistent_capitalization` — whose own evidence already
deterministically enumerates every valid candidate value
(`distinct_casings`), so the only remaining judgment is which is
canonical — `GET .../rule-proposal` additionally attempts a validated
AI-assisted proposal once slice 1 reports `available: false` **and**
`Settings.llm_provider != "disabled"`: a real provider may only choose
one of that finding's own already-observed candidate values (a closed,
per-request-enumerated JSON-Schema contract, `rule_generation_v1` —
never free text, never an invented value). An accepted choice executes
an `accepted_values` candidate rule (`provenance: "ai_assisted"`)
against the analysis's real current rows before returning it, exactly
like slice 1's own offer-never-persist contract. Disabled, rejected, or
a provider error falls back to slice 1's identical `available: false`
response, unchanged. `ai_call_status` discloses this specific request's
own AI-assisted attempt, mirroring `GET .../explanation`'s own
established four-value contract exactly:
`"not_configured"`/`"attempted_accepted"`/`"attempted_rejected"`/
`"attempted_provider_error"` — `"not_configured"` covers both "AI
disabled" and "this detector is not AI-assistable" (including every
case where slice 1 already found a deterministic mapping).
`evidence_sent_to_model` is `true` whenever `ai_call_status` is any
`attempted_*` value. The 2 remaining permanently-excluded categories
(`cross_field.line_total_mismatch`,
`security.possible_llm_prompt_injection`) stay excluded from the
AI-assisted path too — a `RULE-01` rule-type/regex-length structural
limit AI cannot repair — and any detector id without a dedicated
`explanation.guidance` template. `POST .../rules` accepting an
AI-assisted proposal persists `provenance: "ai_assisted"`; every other
`source_finding_id` still persists `provenance: "detector_generated"`,
unchanged.

**Implemented (`RULE-02` slice 3, `WP-082`, `RULE-02` now feature-complete):**
`statistical.suspiciously_constant_column` moves from AI-assist
consideration to the deterministic mapping table: a constant column's
own `distinct_count == 1` invariant means exactly one observed value
exists — no canonical-choice judgment is needed, so this stays fully
deterministic, never AI-assisted. `GET .../rule-proposal` now returns
`available: true` for this detector with a real, already-executed
`accepted_values` candidate whose sole value is that column's own
verbatim observed constant; `POST .../rules` persists
`provenance: "detector_generated"`, identical to the other 9 slice-1
categories. Every one of `RULE-02`'s 13 detector categories now has a
final generation outcome: 10 deterministic, 1 AI-assisted, and 2
permanently unsupported for the structural reasons stated above.

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

**Implemented (`EXP-01` slice 1):** both routes are real and return the
same document, rendered as JSON (`application/json`, file
`rules-{analysis_id}.json`) or YAML (`application/yaml`, file
`rules-{analysis_id}.yaml`), as an attachment. The document has
`export_type` (`validation_rules`), `export_schema_version` (`"1"`),
`analysis_id`, `rule_count`, `excluded_rule_count` and `rules`. Only
*validated* rules are exported: enabled, with a latest execution result
that has no error. Every other rule is withheld and only counted in
`excluded_rule_count`. Each rule carries its identity, `severity`,
`rule_type`, `columns` (`name`, `key`), `null_handling`, the parameters
its type uses, `provenance`, `source_finding_ids`, and aggregate
`validation` counts (`pass_count`, `fail_count`, `skipped_count`). No
example failures, row numbers, timestamps or other dataset row content
are exported, and output is byte-identical for the same analysis. A
known analysis that is not `COMPLETED` is `409 INVALID_ANALYSIS_STATE`;
an unknown one is `404 ANALYSIS_NOT_FOUND`.

**Implemented (`EXP-01` slice 3):** the four report routes are real. `POST`
takes an optional body `{"options": {"include_dismissed": false,
"include_technical_appendix": false, "include_bounded_examples": false}}`
(each defaults to `false`; an unknown option is `422`) and returns `201`
with the report's metadata: `report_id`, `analysis_id`, `generated_at`,
`options`, `schema_version` and `content_sha256`. The Markdown is rendered
once, at creation, and stored; `GET` metadata, the list (in creation
order) and `download` serve the stored snapshot and never re-render, so a
later review or rule change does not alter an existing report. `download`
returns the exact stored bytes as `text/markdown` with an attachment
disposition, and their SHA-256 equals `content_sha256`. A known analysis
that is not `COMPLETED` is `409 INVALID_ANALYSIS_STATE` on `POST`; an
unknown analysis is `404 ANALYSIS_NOT_FOUND` on every route; an unknown
report, or one belonging to a different analysis, is `404 REPORT_NOT_FOUND`.
Reports are stored in a new additive `reports` table. The report's
AI-processing security section is built from the analysis's AI enrichment
record (`EXP-01` slice 4, `D-047`): counts of attempted calls by outcome,
whether evidence or confirmed context may have been sent, the model
location and the protections that hold on every call path. An analysis
created before recording existed has no record, and its reports state that
enrichment is not recorded and make no statement about use (`D-046`).

**Rendering (`EXP-01` slice 2):** the Markdown report itself is rendered by
`trusttable_backend.exports.report_markdown`. The three request options
map as follows:
*include dismissed findings* adds dismissed findings and their reasons;
*include technical appendix* adds detector versions, confidence, evidence
identifiers and rule provenance; *include bounded examples* adds detector
observation text (which can quote dataset values, so it is withheld
otherwise) and up to five affected row numbers per finding. The report has
the sections of `docs/product-requirements.md` §8.9 in a fixed order and no
render timestamp, so identical input yields identical bytes. Its
AI-processing security section reports only recorded state and says when
per-request AI enrichment is not recorded (`D-046`).

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
- REPORT_NOT_FOUND
- RELATIONSHIP_NOT_FOUND
- RELATIONSHIP_VERSION_CONFLICT
- RELATIONSHIP_WITHDRAWN
- ACTIVE_RELATIONSHIP_LIMIT_REACHED
- RELATIONSHIP_VERSION_LIMIT_REACHED
- ANALYSIS_RELATIONSHIP_VERSION_LIMIT_REACHED
- INVALID_RELATIONSHIP_TRANSITION
- COLUMN_REFERENCE_NOT_IN_ANALYSIS
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

## 16. Planned API additions for the UI/UX redesign (provisional; planned, not built)

> **Status.** Nothing in this section exists. It records what the owner-confirmed
> redesign (`docs/decision-log.md` D-066) needs, so that no screen is designed on an
> assumed capability. Routes, field names and mechanisms are provisional and are
> fixed in each slice's specification, after a fresh independent review. Where more
> than one valid mechanism exists, none is approved here.

Existing routes, including direct upload `POST /analyses`, keep their contracts.

| Need | Planned capability | Notes (requirements, not mechanisms) |
|---|---|---|
| Configure step (`UX-02`) | Stage a file once, inspect it, then Run the analysis over the exact staged bytes | Single-use opaque reference; server-computed integrity hash verified at consume; bounded count, bytes and expiry; startup and lazy cleanup; atomic consume; no durable Dataset; the same validation and parser limits as direct upload through one shared ingestion path; inspection returns worksheets, shape, readability problems and warnings, never cell values; this supersedes the unbuilt `POST /datasets/inspect` description in section 7 |
| AI status (`UX-02`, `UX-09`) | `GET /ai/status` (section 4 describes it and it is not built) | Honest enabled, ready and model-identity state; path-free and address-free labels; an abstract status that does not assume where a runtime runs |
| History (`UX-03`) | List analyses; rerun as a new analysis from stored content; look up whether the exact same file was analysed before | The lookup is not a dataset identity; it reflects only analyses that still exist; no integrity hash in normal-user responses |
| Dashboard (`UX-04`) | Aggregates where client derivation from existing data is insufficient | Proposal-level |
| Persisted AI enrichment (`UX-05`) | Start or resume, read status and read a saved result per finding, split from the deterministic explanation | Deterministic content never waits for a model call; the result is bound to the finding, confirmed-context version, model identity and prompt or contract version and is reported stale when the binding changes; start and status must not depend on one long request; bounded concurrency; saved output is deleted with its analysis |
| Inspector (`UX-06`) | Bounded, finding-scoped row windows, including observation example rows | Server-side bounds; no shared-cache storage; unchanged privacy boundary (D-025); window and paging limits are set only after the performance spike |
| Settings (`UX-08`) | Read effective settings with their source (deployment override, stored, default); write allowlisted, typed, versioned stored settings; reset to default | Computed server-side; a stored value never exceeds a deployment override or a security or resource limit; unknown keys and values rejected; write-path protection and fail-closed behavior; a narrow Advanced response may expose effective runtime and model configuration and raw paths and URLs never appear in analysis, finding, report or other shareable responses |

Behavior preserved: `GET .../findings/{finding_id}/explanation` and
`GET .../findings/{finding_id}/rule-proposal` currently perform a model call per
request where configured; the redesign must not make a screen depend on that, and the
existing contracts stay until a slice specification changes them deliberately.

Not planned in this redesign: file-reading options (`ING-05`), rule creation, editing
or reuse across analyses (`RULE-04`), selectable analysis methods, a general dataset
browser, and any product-managed model or runtime management (`LAI-01`, not approved).
