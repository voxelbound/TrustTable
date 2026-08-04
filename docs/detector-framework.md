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
- duplicate normalized column name
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
- invalid country/region values
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
- status/date conflict
- missing currency in multi-currency data

### AI-processing security

- possible prompt injection
- possible data-exfiltration instruction
- suspicious secret-request text

The latter two may initially map to one detector with evidence subtypes.

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
