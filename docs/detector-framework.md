# TrustTable Detector Framework

## 1. Purpose

Detectors convert deterministic profiles, source data, and confirmed context into evidence-backed candidate findings.

The framework must support a growing catalogue without coupling detectors to FastAPI, SQLAlchemy, React, or model providers.

## 2. Detector contract

Conceptual interface:

```python
class Detector(Protocol):
    metadata: DetectorMetadata
    config_schema: type[BaseModel]

    def supports(self, request: DetectorSupportRequest) -> bool: ...
    def run(self, request: DetectorRunRequest) -> DetectorRunResult: ...
```

## 3. Metadata

Every detector defines:

- stable detector ID
- version
- human-readable name
- category
- description
- applicable inferred types
- required profile fields
- whether raw rows are required
- whether confirmed context is required
- whether ingest facts are required (additive; defaults to no; `docs/decision-log.md` D-062)
- default configuration
- performance classification
- documented limitations

Example ID:

```text
consistency.line_total_mismatch
```

IDs are never reused for materially different semantics.

## 4. Categories

- structural
- completeness
- consistency
- validity
- statistical
- cross_field
- ai_processing_security

## 5. Input model

A detector receives only the inputs it declares:

- dataset metadata
- relevant column profiles
- bounded source columns or rows
- row-reference mapping
- confirmed context
- ingest facts (optional and only if declared: an immutable, in-memory projection of
  four parser warning codes holding counts and bounded references, never a parser
  message or a cell value; a detector that requires them is skipped, never run,
  when none are supplied)
- detector configuration
- analysis timestamp
- security exposure state

A detector must not reach into global application state.

## 6. Output model

```text
DetectorRunResult
├── status
├── findings[]
├── evidence[]
├── warnings[]
├── execution metrics
└── safe failure
```

A finding candidate includes:

- detector ID and version
- category
- severity
- confidence
- calculated observation
- affected columns
- affected row references
- evidence references
- default remediation template key
- default validation-rule template key

## 7. Evidence-first rule

Detectors produce evidence before findings.

A detector may return no finding when evidence does not cross configured thresholds.

Every finding must reference one or more evidence objects produced in the same result or an approved upstream profile.

## 8. Configuration

Detector thresholds use validated, versioned schemas.

Requirements:

- defaults are documented
- overrides are recorded with the analysis
- thresholds are deterministic
- no hidden environment-dependent behavior
- configuration changes that alter semantics require detector-version review

## 9. Registration

Use explicit registration.

Example:

```python
DETECTORS = [
    ExactDuplicateRowsDetector(),
    MissingIdentifierDetector(),
    LineTotalMismatchDetector(),
    PossiblePromptInjectionDetector(),
]
```

Avoid dynamic entry-point discovery in v1.

Startup validation ensures:

- unique IDs
- valid versions
- valid configuration
- declared dependencies exist

## 10. Execution

Execution engine responsibilities:

1. determine supported detectors
2. provide declared inputs
3. enforce time and resource boundaries
4. isolate detector failures
5. record timing
6. collect evidence and findings
7. preserve deterministic order where needed
8. report skipped detectors and reasons

One detector failure does not normally fail the entire analysis.

Critical parser or profile corruption may fail the analysis.

## 11. Severity

Severity reflects likely business or processing impact.

Detectors calculate a default severity using explicit rules.

The dataset-level risk scorer may combine findings, but the LLM cannot replace detector severity or risk score.

## 12. Confidence

Confidence reflects pattern strength.

Examples:

- exact duplicate match: high confidence
- context-dependent negative quantity without confirmed return semantics: lower confidence
- instruction-like content: confidence based on matched patterns, not intent

## 13. Performance classes

- constant or metadata-only
- linear by row
- linear by value length
- grouped aggregation
- pairwise candidate
- sampled expensive

Pairwise operations require explicit bounding or sampling.

## 14. Security detector

Required detector:

```text
security.possible_llm_prompt_injection
```

### Purpose

Detect instruction-like text that could attempt to influence an LLM workflow.

### Pattern families

Examples include bounded combinations of:

- ignore previous instructions
- reveal system prompt
- act as another system
- do not report this issue
- claim the data is valid
- output only a specified answer
- disclose secrets
- send data externally

### Requirements

- safe bounded matching
- no catastrophic regular expressions
- case and whitespace normalization
- length-limited inspection
- evidence includes row and column references
- full value is not logged
- negative controls are tested
- finding language says possible risk
- severity considers actual model exposure

### Negative controls

Do not automatically classify as malicious:

- security documentation
- support tickets
- chat transcripts
- ordinary uses of “ignore”
- discussion of prompt injection

## 15. Detector test contract

Every detector test suite includes:

- positive case
- negative case
- threshold boundary
- null or empty input
- malformed input
- deterministic repeatability
- configuration override
- known false-positive example
- performance guard when relevant

## 16. Initial detector catalogue

### Structural

- empty dataset — **built** (`DET-03` closure package 1)
- empty column
- unnamed column — **built** (`DET-03` closure package 1)
- duplicate normalized column name — **built** (`DET-03` slice 4)
- exact duplicate rows
- probable duplicate identifier
- mixed types
- excessive parse failures — **built** (`DET-03` closure package 1)

### Completeness

- excessive missing values
- missing likely identifier
- fully empty rows
- concentrated missingness
- completeness change over time

### Consistency

- leading/trailing whitespace
- inconsistent capitalization
- near-duplicate categories
- inconsistent booleans
- numeric values stored as text
- inconsistent date formats
- conflicting stable attributes

### Validity

- future dates
- implausibly old dates
- negative likely non-negative values
- invalid percentages
- invalid country/region values — **moved out of `DET-03`, not built** (see
  "Design outcome" below)
- invalid email shape where relevant

### Statistical

- extreme outliers
- suspiciously constant columns
- high-cardinality categories
- unexpected rarity
- distribution shift
- identifier-like measure

### Cross-field

- line total mismatch
- discount inconsistency
- tax inconsistency
- start date after end date
- status/date conflict — **moved out of `DET-03`, not built** (see "Design
  outcome" below)
- missing currency in multi-currency data

### AI-processing security

- possible prompt injection
- possible data-exfiltration instruction
- suspicious secret-request text

The latter two may initially map to one detector with evidence subtypes.

### Catalogue status

> **Annotation (2026-10-02, `DET-03` slices 1 to 3; `docs/decision-log.md`
> D-054, D-055, D-056):** 19 detectors are built and registered: the 13 of
> `DET-02` and `DET-SEC-01`, plus `completeness.fully_empty_rows` (rows blank
> in every column), `consistency.inconsistent_booleans` (a column whose values
> are all boolean tokens written in more than one spelling family),
> `validity.implausibly_old_dates` (ISO dates before 1900-01-01),
> `validity.invalid_email_shape` (values in an email-named column that cannot
> have the shape `local@domain.tld`; counts and row numbers only, never a
> value), `consistency.numeric_values_stored_as_text` (a column of numbers
> written with currency symbols, percent signs or thousands separators; codes
> such as zero-padded values and phone numbers are never read as numbers) and
> `consistency.near_duplicate_categories` (category values that differ only by
> punctuation or internal spacing; casing-only and outer-whitespace-only
> differences stay with the existing detectors).
>
> **Annotation (2026-10-04, `DET-03` slice 4; `docs/decision-log.md` D-058):**
> a 20th detector is built and registered,
> `structural.duplicate_normalized_column_name` (two or more columns whose names
> are the same once case, spacing and punctuation are ignored; names are
> compared as letters, digits and combining marks in any script, not by the
> parser's ASCII key;
> column names only, never a cell value). Every other entry in the
> lists above is **planned and not built**;
> several need confirmed context or profile facts that do not exist yet.
> `DET-03` is in progress, not complete.
>
> **Annotation (2026-10-04, `DET-03` confirmed-relationship foundation;
> `docs/decision-log.md` D-060):** the stored, versioned record of user-stated
> `start_end_date` relationships is built, with routes to confirm, replace,
> withdraw and read it. **No detector reads it, no gate or observation exists, and
> the detector count is unchanged at 20.** Its `check_status` is always
> `not_active`, which never means a check passed. The context-bound entries below
> stay **planned and not built**.
>
> **Annotation (2026-10-05, `DET-03` closure package 1; `docs/decision-log.md`
> D-062):** three detectors are built and registered, bringing the catalogue to 23:
> `structural.empty_dataset` (a header with no data rows; the parsers accept such a
> file, so detector execution owns the case), `structural.unnamed_column` (blank
> header cells) and `structural.excessive_parse_failures` (an excessive share of rows
> with the wrong number of fields, or of XLSX cells read as empty or holding an error
> value). The last two read only the in-memory four-code ingest-facts projection;
> nothing is persisted or exposed, and no detector reads a parser message or a cell
> value. None proposes a validation rule. **`DET-03` is in progress, not complete**;
> the catalogue is not complete.

### Design outcome (2026-10-02, documentation only)

This subsection records the confirmed `DET-03` design outcome (`docs/decision-log.md`
D-057). It changes no code, tests, schemas or detector behavior. Items marked
"open" are deliberately undecided.

**Per-entry status.** Every catalogue entry has exactly one status:
*implemented* (the 20 built detectors listed above), *planned* (stays in
`DET-03`), or *moved* (removed from `DET-03` with a traceable note). Moved
entries are never counted as completed, and `DET-03` completion language counts
implemented entries only.

| Entry | Status | Note |
|---|---|---|
| invalid country/region values | **moved** | Moved, not dropped, into two separately named proposed capabilities: *standards policy* and *semantic category harmonization* (below). |
| status/date conflict | **moved** | Moved into a named business-rule follow-up until a way to capture owner-stated categorical rules exists. |
| duplicate normalized column name | **implemented** (slice 4, D-058) | Finding; the 20th built detector. |
| unnamed column; empty dataset | planned | Findings (meaning-independent structural defects). Unnamed column depends on the ingest-facts record; empty dataset only if zero-row handling is verified reachable (open). |
| mixed types; inconsistent date formats; high-cardinality categories; unexpected rarity; concentrated missingness | planned | **Observations by default**, not findings. |
| start date after end date; discount inconsistency; tax inconsistency; missing currency; conflicting stable attributes; probable duplicate identifier; identifier-like measure | planned | Context-bound; depend on the confirmed-context foundation. |
| completeness change over time; distribution shift | planned | Context-bound and time-based; neutral observation unless a confirmed expectation is violated. |
| possible data-exfiltration instruction; suspicious secret-request text | planned | Findings after a security review and an extended adversarial suite. |
| excessive parse failures | planned | Re-framed by the ingest-facts record (below): "parse failure" is not an umbrella concept. |

**Finding versus observation.** A *Finding* is produced by a detector, has its
own identity, provenance and evidence, and may affect trust scoring. An
*Observation* is based only on facts observable in the data, makes no claim
that a business role is true, never affects trust scoring, may suggest a
possible interpretation, and is intended to be dismissible or suppressible
(dismissal and suppression are a later design: `docs/decision-log.md` D-059 ships
the first observation kind read-only and without dismissal). An observation is
never promoted or converted into a finding; a later finding is a new object and
the observation stays unchanged. A meaning-independent defect may become a
finding; a pattern whose significance depends on business meaning stays an
observation until sufficient confirmed context or an explicit expectation
exists. The planned observation kinds are processing-limit, value-evidence,
not-checked, standards-advisory and equivalence-suggestion; the final closed
vocabulary is open. D-059 decides the first, minimal step only: a single
`NOT_CHECKED` kind, stored per analysis with a read-only route, shipped together
with its first producer (the start-date-after-end-date detector) and never counted
by trust scoring; no other kind is decided.

**Confirmed-context rule for context-bound detectors.** A context-bound
detector runs only when every role it declares is confirmed or corrected,
unambiguous, type-compatible and not stale (and, for discount and tax, the
interpretation is confirmed). Otherwise it is *not evaluated*: no finding, trust
score unchanged, and the run is recorded as NOT EVALUATED, never as passed. When
the skip is because confirmed context is stale, conflicting or invalid, a
neutral NOT_CHECKED observation is mandatory; when a role was simply never
confirmed it is optional (D-059 decides no observation record is created then;
the analysis summary carries a derived, non-persisted count of checks awaiting
confirmed context instead). A detector never runs from a suggestion and never
infers a role from a name, label, value pattern or AI output. **Most
context-bound detectors therefore stay inactive until a confirmation path
ships, and their tests until then are contract-level, not end-to-end.**

**Context-bound contracts that remain in `DET-03`** (exact formulas, tolerances
and thresholds are specified at each detector's own design):

- *Start date after end date:* confirmed, distinct, date-typed start and end
  roles; equality is not a violation unless a confirmed interpretation says so;
  rows blank in either role are counted as not evaluated. **Planned, not built.**
  D-059 fixes how the roles are confirmed: a user-stated `start_end_date`
  relationship, each side a `ColumnReference` within one immutable analysis,
  versioned, never inferred from a name. The same column on both sides, a column in
  several relationships, and non-date or mixed-type columns are stored (built,
  D-060) and judged by the gate as `NOT_CHECKED` (the gate is not built). The detector's severity, evidence cap and
  finding-to-version link are specified in the execution package's design, which
  also must define what a conflicting confirmation is.
- *Discount inconsistency:* confirmed gross, discount and net roles, a confirmed
  discount interpretation (percentage, fraction or absolute) and relationship;
  the finding states the interpretation and tolerance used.
- *Tax inconsistency:* confirmed base, tax and total roles and confirmed tax
  semantics (rate or amount, inclusive or exclusive, rounding); no inferred
  formula.
- *Missing currency:* a confirmed currency field, or a confirmed dataset-level
  currency; applies only where the confirmed currency field shows more than one
  currency and stays silent under a confirmed dataset-level currency. This
  narrows the catalogue wording and is an owner-visible product-behavior choice.
- *Conflicting stable attributes:* a confirmed key role, confirmed attribute
  roles and an explicit confirmed expectation that the attribute is stable per
  key.
- *Probable duplicate identifier:* before confirmation only an observation of
  observed facts; after the identifier role is confirmed a separate finding.
- *Identifier-like measure:* an observation by default; a finding only with an
  explicit confirmed expectation.

**Time-based checks.** Comparison is within the uploaded file on a confirmed
date role, with disclosed period construction and windows and a stated minimum
sample per period (silent when evidence is insufficient). A confirmed time axis,
an observed change, a confirmed business expectation and a finding caused by
violating that expectation are four separate concepts; a change is never a
defect by itself. Comparison with a previous upload is outside this design
until durable dataset identity exists.

**Ingest-facts record.** A typed, parser-neutral, immutable record with a fixed
vocabulary and consistent semantics across CSV and XLSX; no cell values, only
counts and bounded row or column references; each fact states its scope and
whether evidence is complete-file or sampled; "not applicable", "zero observed"
and "not evaluated" stay distinct. Categories: source-structure facts,
spreadsheet or source-cell facts, TrustTable processing-limit facts (not defects
in the user's data and never ordinary findings), and value-level interpretation
facts. An originally blank header stays an explicit fact after the parser
assigns `column_<n>`. The ingest layer owns the immutable source fact; the
detector owns whether it becomes a finding, with no double reporting.

**Moved capability 1 — standards policy (proposed, not committed).** Per column
Off / Advisory / Enforced; no standard by default (no standard selected means
unknown, not invalid); optional user-selected starter standards, never applied
automatically and never treated as universal truth; optional custom reference
lists; local aliases and exceptions; suppression and dismissal. Advisory output
is excluded from trust scoring; only explicitly confirmed Enforced deviations
become findings, worded "does not match your selected standard". Region meaning
is never inferred from a column name (EMEA, DACH, Nordics and internal codes are
legitimate business vocabulary). Which starter standards ship, when, and how
Advisory suppression is keyed are open.

**Moved capability 2 — semantic category harmonization (proposed, not
committed).** Generic across countries, regions, organizations, products,
statuses and other categorical dimensions. Candidates come deterministically
where possible (the near-duplicate category evidence is a candidate input), with
optional local-AI assistance that is advisory only. Suggestions stay advisory
until the user confirms; a confirmed equivalence becomes durable business
context. "Treat as equivalent" (analysis treats values as one concept, source
data untouched) stays separate from "normalize" (changes or exports toward a
canonical value; needs an explicit canonical-value decision). Ambiguous values
(for example Georgia; Congo versus DR Congo) are never silently collapsed, and
values are never merged or rewritten automatically. Wording is "possible
equivalent values". How much local-AI assistance ships first and the candidate
rules are open.

**Standing principles.** Column names and labels may be hints and supporting
evidence but never by themselves define business meaning; naming variants
(`pct`, `%`, `percent`, `rabatt`, `disc`) are the user's terminology and never
correctness issues; built-in standards are never universal truth; value
distribution can support a suggestion but does not establish business meaning.

**Shipped detectors and name-based meaning.** A read-only audit (detector code
plus a text search of profiling and rules; type inference not audited line by
line) found:

- *Require migration to confirmed roles:* `cross_field.line_total_mismatch`
  (default column names and a fixed pricing formula; a historical stopgap) and
  `validity.invalid_percentages` (name contains `pct`, `percent` or `%`, plus a
  numeric-type guard).
- *Compatibility exception to review:* `validity.invalid_email_shape` (name
  contains `email` and at least half of non-blank values already look like
  emails; the value-shape guard materially limits false positives).
- *No name inference:* the structural, completeness, consistency, validity,
  statistical and security detectors not named above. `missing_likely_identifier`
  and `negative_likely_non_negative_values` read meaning from value distribution
  and are to be reviewed under the observation and finding rule.

The standing name principle is therefore **partly unmet by shipped code until
migration**. The name-based detectors are temporary compatibility exceptions with
a migration requirement, not an accepted long-term pattern. Shipped detector
behavior is unchanged by this design. The exit condition (migration of the two
detectors and review of the third, with a compatibility window and a measurable
owner-visible exit) is open.

**Acceptance criteria carried by follow-on items (specified, not built here).**
An executable catalogue check that every entry is implemented or carries a
traceable moved or deferred note; a machine-readable dependency-edge validator;
per-detector negative tests (no context, stale, ambiguous role, type-incompatible
role, unconfirmed interpretation) asserting zero findings, unchanged score and a
NOT EVALUATED record; a scoring-boundary regression test over the
observation-kind registry; and a migration plan for demo and benchmark fixtures.

### Closure boundary (2026-10-05, `docs/decision-log.md` D-061; documentation only)

`DET-03` is retitled **Core detector catalogue**. This subsection records the
approved closure boundary. It supersedes the "planned (stays in `DET-03`)" column
of the table above wherever the two differ; the table above is history for the
2026-10-02 design. Nothing marked planned here is built, and no document may say
detection is active for it.

**Target:** 27 registered detectors covering 28 of the 41 catalogue entries. One
planned security detector covers two entries (data-exfiltration instruction and
suspicious secret-request text), which is why detectors and entries differ. The
package-1 investigation (D-062) found that the empty-dataset case is **not**
parser-owned, so the 26-detector alternative no longer applies and the target stays
27 detectors covering 28 entries. 13 entries are carried by named successor items.
No entry is dropped.

**Dispositions.** BUILT: registered before closure (20). BUILT BY CLOSURE: planned
for `DET-03` closure (8 entries, 7 detectors), of which closure package 1 has built 3
entries and 3 detectors (D-062) and 5 entries and 4 detectors are **still not built**.
MOVED: carried by a named successor item (11). MOVED PREVIOUSLY: moved by D-057 (2).
20 + 8 + 11 + 2 = 41. **Registered today: 23 detectors.** Names of detectors not yet
built below are working names; each is fixed in its own package.

| # | Catalogue entry | Disposition | Detector or carrier |
|---|---|---|---|
| 1 | empty dataset | BUILT BY CLOSURE (built, package 1) | `structural.empty_dataset` (the parsers accept a header-only file, so detector execution owns the case; D-062) |
| 2 | empty column | BUILT | `structural.empty_column` |
| 3 | unnamed column | BUILT BY CLOSURE (built, package 1) | `structural.unnamed_column` |
| 4 | duplicate normalized column name | BUILT | `structural.duplicate_normalized_column_name` |
| 5 | exact duplicate rows | BUILT | `structural.exact_duplicate_rows` |
| 6 | probable duplicate identifier | MOVED | DET-04 (observation form), DET-05 (finding form) |
| 7 | mixed types | BUILT BY CLOSURE | `structural.mixed_types` (observation) |
| 8 | excessive parse failures | BUILT BY CLOSURE (built, package 1) | `structural.excessive_parse_failures` |
| 9 | excessive missing values | BUILT | `completeness.excessive_missing_values` |
| 10 | missing likely identifier | BUILT | `completeness.missing_likely_identifier` |
| 11 | fully empty rows | BUILT | `completeness.fully_empty_rows` |
| 12 | concentrated missingness | BUILT BY CLOSURE | `completeness.concentrated_missingness` (observation) |
| 13 | completeness change over time | MOVED | DET-06 |
| 14 | leading/trailing whitespace | BUILT | `consistency.leading_trailing_whitespace` |
| 15 | inconsistent capitalization | BUILT | `consistency.inconsistent_capitalization` |
| 16 | near-duplicate categories | BUILT | `consistency.near_duplicate_categories` |
| 17 | inconsistent booleans | BUILT | `consistency.inconsistent_booleans` |
| 18 | numeric values stored as text | BUILT | `consistency.numeric_values_stored_as_text` |
| 19 | inconsistent date formats | BUILT BY CLOSURE | `consistency.inconsistent_date_formats` (observation) |
| 20 | conflicting stable attributes | MOVED | DET-05 |
| 21 | future dates | BUILT | `validity.future_dates` |
| 22 | implausibly old dates | BUILT | `validity.implausibly_old_dates` |
| 23 | negative likely non-negative values | BUILT | `validity.negative_likely_non_negative_values` |
| 24 | invalid percentages | BUILT | `validity.invalid_percentages` (name-based; migration is DET-05) |
| 25 | invalid country/region values | MOVED PREVIOUSLY | STD-01 and HARM-01 (D-057) |
| 26 | invalid email shape | BUILT | `validity.invalid_email_shape` (name-based; review is DET-05) |
| 27 | extreme outliers | BUILT | `statistical.extreme_outliers` |
| 28 | suspiciously constant columns | BUILT | `statistical.suspiciously_constant_column` |
| 29 | high-cardinality categories | MOVED | DET-04 |
| 30 | unexpected rarity | MOVED | DET-04 |
| 31 | distribution shift | MOVED | DET-06 |
| 32 | identifier-like measure | MOVED | DET-04 (observation form), DET-05 (finding form) |
| 33 | line total mismatch | BUILT | `cross_field.line_total_mismatch` (name-based; migration is DET-05) |
| 34 | discount inconsistency | MOVED | DET-05 |
| 35 | tax inconsistency | MOVED | DET-05 |
| 36 | start date after end date | MOVED | CCX-01 (first consumer of the confirmed-relationship record) |
| 37 | status/date conflict | MOVED PREVIOUSLY | RULE-03 (D-057) |
| 38 | missing currency in multi-currency data | MOVED | DET-05 |
| 39 | possible prompt injection | BUILT | `security.possible_llm_prompt_injection` |
| 40 | possible data-exfiltration instruction | BUILT BY CLOSURE | `security.possible_exfiltration_or_secret_request` (evidence subtype) |
| 41 | suspicious secret-request text | BUILT BY CLOSURE | the same detector as #40 (evidence subtype) |

Counts: BUILT 20 entries and 20 detectors; BUILT BY CLOSURE 8 entries and 7
detectors (3 entries and 3 detectors built by package 1, 5 entries and 4 detectors
not yet built); MOVED 11; MOVED PREVIOUSLY 2. Entries #6 and #32 each have an observation
form (DET-04) and a later confirmed-finding form (DET-05); they are counted once, as
MOVED.

**Closure packages (package 1 built, packages 2 to 4 planned).** Package 1,
structural and ingest closure, **built** (D-062): the zero-row and header-only
investigation, then `structural.empty_dataset`; an immutable, in-memory parser-warning projection limited to four
codes (`parsing.empty_column_name`, `parsing.ragged_row`,
`parsing.xlsx_formula_without_cached_value`, `parsing.xlsx_error_value`) carrying
counts and bounded references only, never a message or a cell value, and reaching a
detector only through an additive optional input behind a metadata flag that defaults
to off (facts absent means the detector is skipped, never passed);
`structural.unnamed_column`; `structural.excessive_parse_failures`, which excludes
truncation caused by a TrustTable processing limit because that is not a defect in
the user's data. No persisted ingest-facts record. Package 2, observation and
value-evidence slice: the minimal Observation foundation (a type with no severity,
confidence or priority, one closed kind `value_evidence`, an additive stored list on
the analysis record, a read-only route and a read-only results-UI list) and its three
producers. Package 3, security detector slice: the adversarial suite is extended
first, then one detector with two evidence subtypes, bounded and redacted evidence,
"possible risk" wording and a recorded Security Reviewer approval. Package 4,
closure: an executable catalogue-status check against the table above, document
reconciliation and the closure report.

**Observation boundary for package 2.** Observations stay neutral and are never
counted by trust scoring or priority, never enter an AI payload, and are excluded
from exports and reports for now. That exclusion is an invariant enforced by a
negative allowlist test that fails if an Observation field reaches score, priority,
an AI payload, an export or a report; it does not rely on the absence of wiring. The
extension seam is that a later kind, such as the `NOT_CHECKED` kind CCX-01 adds, is a
new kind and never a change to `value_evidence`. The package also records the
provisional Observation API in the API specification and the domain model, so later
dismissal, suppression, history and further kinds can be added without a breaking
change. No `DET-03` detector reads confirmed relationships.

**Carried by successors (placement open).** DET-04: value-distribution
observations (high-cardinality categories, unexpected rarity, and the observation
forms of probable duplicate identifier and identifier-like measure). CCX-01:
confirmed-context execution, which includes the gate, the durable scheduler, stale-run
recovery, the awaiting-confirmation summary, `NOT_CHECKED` and the start-date-after-
end-date detector, and which owns the two open decisions (a conflicting
confirmation; a withdrawn relationship). CCX-02: the confirmation screen. DET-05:
context-bound detectors (discount, tax, missing currency, conflicting stable
attributes, the confirmed-finding forms of #6 and #32) and the migration of the
name-based detectors. DET-06: time-based observations (completeness change over
time, distribution shift). OBS-02: observation dismissal, suppression, history,
export inclusion and further kinds. ING-04: a persisted ingest-facts record and
processing-limit facts. STD-01, HARM-01 and RULE-03: as already named.

## 17. Detector lifecycle

```text
proposed
   ↓
implemented
   ↓
unit tested
   ↓
synthetic evaluation
   ↓
documented
   ↓
enabled by default
   ↓
versioned changes
```

A detector is not enabled by default until its acceptance and evaluation thresholds are approved.
