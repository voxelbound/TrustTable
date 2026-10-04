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

- empty dataset
- empty column
- unnamed column
- duplicate normalized column name — **built** (`DET-03` slice 4)
- exact duplicate rows
- probable duplicate identifier
- mixed types
- excessive parse failures

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
possible interpretation, and can be dismissed or suppressed. An observation is
never promoted or converted into a finding; a later finding is a new object and
the observation stays unchanged. A meaning-independent defect may become a
finding; a pattern whose significance depends on business meaning stays an
observation until sufficient confirmed context or an explicit expectation
exists. The planned observation kinds are processing-limit, value-evidence,
not-checked, standards-advisory and equivalence-suggestion; the final closed
vocabulary and its persistence and API surface are open.

**Confirmed-context rule for context-bound detectors.** A context-bound
detector runs only when every role it declares is confirmed or corrected,
unambiguous, type-compatible and not stale (and, for discount and tax, the
interpretation is confirmed). Otherwise it is *not evaluated*: no finding, trust
score unchanged, and the run is recorded as NOT EVALUATED, never as passed. When
the skip is because confirmed context is stale, conflicting or invalid, a
neutral NOT_CHECKED observation is mandatory; when a role was simply never
confirmed it is optional. A detector never runs from a suggestion and never
infers a role from a name, label, value pattern or AI output. **Most
context-bound detectors therefore stay inactive until a confirmation path
ships, and their tests until then are contract-level, not end-to-end.**

**Context-bound contracts that remain in `DET-03`** (exact formulas, tolerances
and thresholds are specified at each detector's own design):

- *Start date after end date:* confirmed, distinct, date-typed start and end
  roles; equality is not a violation unless a confirmed interpretation says so;
  rows blank in either role are counted as not evaluated.
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
