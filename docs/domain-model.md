# TrustTable Domain Model

## 1. Purpose

This document defines the business concepts used across the backend, frontend, persistence, tests, reports, and AI workflows.

It is intentionally independent of SQLAlchemy, FastAPI, React, and Ollama.

## 2. Aggregate overview

```text
Dataset
   │
   └── Analysis
         ├── DatasetProfile
         ├── DatasetContext
         │     ├── ContextHypothesis
         │     ├── ClarificationQuestion
         │     └── ClarificationAnswer
         ├── Finding
         │     ├── Evidence
         │     ├── AIInterpretation
         │     ├── RemediationOption
         │     └── FindingReview
         ├── ValidationRule
         │     └── RuleExecutionResult
         ├── Report
         └── AnalysisEvent
```

## 3. Shared value objects

### AnalysisId

An opaque, unguessable identifier.

Invariants:

- globally unique within an installation
- never derived from a filename
- safe for URLs
- immutable

### ColumnReference

Identifies a source column.

Fields:

- original name
- normalized internal key
- ordinal position

Invariants:

- original name is preserved for display
- internal key is unique within the parsed dataset
- references must resolve before persistence or export

### RowReference

Identifies an affected source row without embedding the row itself.

Fields:

- stable internal row number
- optional source line number
- optional deterministic row fingerprint

### EvidenceId

Stable identifier for one computed evidence object.

### DetectorId

Stable, namespaced identifier such as:

```text
consistency.line_total_mismatch
security.possible_llm_prompt_injection
```

### Provenance

Allowed values:

- calculated
- ai_interpretation
- user_confirmed
- user_corrected
- deterministic_fallback

### Severity

Allowed values:

- critical
- high
- medium
- low
- informational

### Confidence

A number from 0 through 1 representing confidence that an observed pattern is a genuine quality concern.

It must not be described as the probability of business loss.

## 4. Dataset

### Purpose

Represents one uploaded or generated tabular data source.

### Fields

- dataset ID
- original filename
- sanitized storage filename
- format
- byte size
- content hash
- selected worksheet
- created timestamp
- deletion timestamp
- storage location
- source type: upload or bundled demo

### Invariants

- uploaded content is immutable
- original file is never overwritten
- macro-enabled files are rejected
- storage path is never user-controlled
- deleted datasets cannot start new analyses

### Lifecycle

```text
received → validated → stored → analyzed → deleted
```

## 5. Analysis

### Purpose

Represents one execution of TrustTable against a dataset using a specific configuration and software version.

### Fields

- analysis ID
- dataset ID
- state
- current stage
- application version
- detector configuration version
- prompt-template versions
- model provider
- model identifier
- model location
- sample-transmission setting
- created, started, completed, failed, cancelled timestamps
- safe failure code and message
- retry source analysis ID, when applicable

### States

- queued
- validating
- parsing
- profiling
- detecting
- inferring_context
- awaiting_confirmation
- finalizing
- completed
- failed
- cancelled
- deleted

### Invariants

- completed facts are immutable
- cancelled analyses cannot transition to completed
- deleted analyses cannot be retrieved
- active analyses interrupted by restart become failed
- retry creates a new analysis or a clearly versioned attempt
- deterministic results exist independently from AI output

## 6. ParsedDataset

### Purpose

In-memory representation used by profiling and detectors.

### Fields

- columns
- row count
- source types
- parsing warnings
- sampling metadata
- row-reference mapping

### Invariants

- parsing never executes formulas, macros, or code
- original column names are preserved
- internal column keys are unique
- resource limits are enforced before expensive analysis

## 7. DatasetProfile

### Purpose

Contains deterministic statistical and structural facts.

### Fields

- schema version
- dataset-level metrics
- column profiles
- calculation scope: full or sampled
- sampling method
- warnings
- timing metadata

### Invariants

- all numeric facts are code-calculated
- sampled metrics are labelled
- empty and all-null columns remain valid profile objects
- no AI-generated value appears in the profile

## 8. DatasetContext

### Purpose

Represents what the dataset means to the user and application.

### Fields

- probable domain
- row grain
- primary entity
- candidate keys
- business dates
- measure roles
- dimensions
- currency behavior
- expected business rules

Each field contains:

- value
- confidence
- inference source
- confirmation state
- evidence references

### Confirmation states

- inferred
- confirmed
- corrected
- unknown

### Invariants

- user-confirmed or corrected values override AI inference
- unknown is a valid outcome
- context does not alter historic deterministic profile facts
- context-dependent detectors record the context version used

## 9. ContextHypothesis

### Purpose

A candidate interpretation generated by deterministic heuristics or AI.

### Fields

- hypothesis ID
- context field
- proposed value
- confidence
- provenance
- evidence references
- rationale
- superseded state

## 10. ClarificationQuestion

### Purpose

Requests business information that can materially affect validity or prioritization.

### Fields

- question ID
- concise text
- explanation
- suggested answers
- inferred default
- affected assumptions
- free-text allowed
- answered state

### Invariants

- no more than five active questions by default
- confirmed facts are not asked again
- questions avoid unnecessary technical terminology
- every question identifies why the answer matters

## 11. ClarificationAnswer

### Fields

- question ID
- selected answer or free text
- answered timestamp
- resulting context changes
- provenance: user_confirmed or user_corrected

## 12. Finding

### Purpose

Represents one potential data-quality or AI-processing risk.

### Fields

- finding ID
- detector ID and version
- category
- severity
- confidence
- deterministic priority score
- manager-facing title
- calculated observation
- affected columns
- affected row count
- affected row percentage
- evidence IDs
- interpretation ID
- remediation IDs
- proposed rule IDs
- review state
- created timestamp

### Invariants

- every finding has at least one evidence object
- deterministic observation remains immutable
- AI cannot remove a finding
- AI cannot modify affected counts
- severity changes are separately recorded and justified
- references must resolve

## 13. Evidence

### Purpose

Provides auditable support for findings.

### Types

- metric
- distribution
- row-set
- category-frequency
- cross-field comparison
- temporal pattern
- security pattern
- detector configuration
- representative sample

### Fields

- evidence ID
- evidence type
- calculation version
- structured payload
- affected columns
- affected row references
- sampled/full scope
- display-safe summary

### Invariants

- evidence is deterministic
- raw sensitive values are not embedded unless explicitly allowed
- report references use display-safe summaries
- row evidence is bounded for display

## 14. AIInterpretation

### Purpose

Stores validated model-generated interpretation without replacing evidence.

### Fields

- interpretation ID
- task type
- schema version
- provider
- model
- prompt version
- input evidence IDs
- untrusted-data exposure summary
- validated output
- validation result
- rejected reason, when applicable
- fallback used
- timing and token metadata where available

### Invariants

- unvalidated output is never presented as completed content
- all evidence and column references resolve
- numeric claims equal supplied facts
- deterministic severity and trust score remain authoritative
- rejected output remains auditable without storing unsafe raw content unnecessarily

## 15. PromptInjectionRisk

A specialization of a security finding.

Additional fields:

- suspicious pattern category
- affected text column
- affected row references
- escaped, truncated display sample
- sent-to-model state
- model location
- protections applied
- model-output rejection state

Invariants:

- suspicious content is never treated as an instruction
- full content is not shown in overview screens
- wording states possible risk, not confirmed malicious intent

## 16. RemediationOption

### Fields

- remediation ID
- action summary
- responsible role
- urgency
- historical correction guidance
- source-system prevention guidance
- risk warning
- verification step
- optional technical example
- provenance

### Invariants

- never states that TrustTable changed the data
- destructive actions include risk warnings
- AI-generated options reference a finding and evidence

## 17. FindingReview

### Fields

- finding ID
- state
- user note
- dismissal reason
- reviewed timestamp

States:

- unreviewed
- confirmed
- dismissed
- needs_investigation

Invariants:

- review does not modify original evidence
- dismissed findings remain auditable
- latest review state is included in exports

## 18. ValidationRule

### Fields

- rule ID
- schema version
- name
- description
- severity
- enabled state
- scope
- rule type
- expression or parameters
- referenced columns
- null handling
- source finding IDs
- provenance

### Invariants

- uses only supported rule types and operators
- references existing columns
- schema validates
- executes successfully before export
- user confirmation is required for exported AI-assisted rules

## 19. RuleExecutionResult

### Fields

- rule ID
- analysis ID
- execution timestamp
- pass count
- fail count
- skipped count
- bounded example failures
- execution duration
- error state

## 20. Report

### Purpose

Represents one generated, immutable export snapshot.

### Fields

- report ID
- analysis ID
- format
- generated timestamp
- included finding review version
- included rule version
- content hash
- storage reference

### Required sections

- dataset summary
- trust assessment
- confirmed context
- priority findings
- review decisions
- remediation
- validation rules
- AI-processing security
- methodology and limitations
- version metadata

## 21. AnalysisEvent

### Purpose

Provides a safe audit trail.

### Event examples

- analysis_created
- stage_changed
- context_confirmed
- model_output_rejected
- finding_reviewed
- rule_executed
- report_generated
- analysis_cancelled
- analysis_retried
- analysis_deleted

### Invariants

- does not include raw rows
- does not include secrets
- preserves event order
- uses safe metadata only

## 22. Aggregate ownership

The Analysis aggregate owns:

- profile
- context
- questions
- findings
- reviews
- rules
- reports
- lifecycle events

The Dataset lifecycle can outlive or contain multiple analyses only when explicitly supported. For v1, the normal UI creates one primary analysis per upload, while retries remain linked attempts.

## 23. Domain invariants summary

1. Deterministic facts are immutable.
2. Every finding has evidence.
3. AI output is optional and subordinate.
4. User-confirmed context overrides inference.
5. Uploaded content is never executed.
6. Suspicious instructions inside data remain data.
7. Original files are never modified.
8. Exported rules must execute.
9. Deleted analyses and artifacts are inaccessible.
10. All externally visible references resolve.
