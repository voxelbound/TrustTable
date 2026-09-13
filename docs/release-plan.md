# TrustTable Release Plan

## v0.1 — Deterministic vertical slice

Deliver:

- repository foundation
- synthetic sales generator
- CSV parsing
- type inference
- core profiles
- initial detectors
- deterministic risk score
- basic full-stack UI
- local Docker execution

No LLM required.

## v0.1.1 — Investigation UX

Deliver:

- row context for row-anchored findings

No LLM required. Does not change v0.2's scope.

## v0.2 — Local AI beta

Deliver, in dependency order:

- provider abstraction
- disabled and mock providers
- persistent local-AI benchmark harness (TrustTable-specific, config-driven; see `docs/decision-log.md` D-032)
- **human decision gate:** runtime, model family/exact model, quantization, and per-hardware-tier default — decided from the benchmark's evidence, not before (`docs/decision-log.md` D-033)
- real local-inference provider (runtime selected via the decision gate above)
- corresponding local runtime/model documentation
- deterministic context hypotheses
- validated context inference
- guided questions
- grounded explanations
- prompt-injection trust boundary

> **Annotation (2026-09-13, `CHG-002`; corrected 2026-09-13, `CHG-003`
> planning alignment):** the specific local runtime (`llama.cpp` vs.
> Ollama) remains an open, human-owned decision — see
> `docs/decision-log.md` D-007's appended review note, D-030–D-032, and
> the sequencing decision D-033. The list above now reads "real
> local-inference provider" rather than "Ollama provider" and includes
> the previously-missing benchmark-harness and human-decision-gate
> entries, sequenced ahead of the real provider per D-032/D-033
> ("runtime and model selection follow from the benchmark harness's
> results"). The prior "Ollama provider" wording is preserved in this
> repository's own git history, not silently erased.

This is the first promoted portfolio release.

## v0.3 — Complete manager workflow

Deliver:

- SQLite persistence
- Alembic migrations
- bounded background work
- cancellation and retry
- finding review
- remediation
- validation rules
- Markdown, JSON, and YAML export
- analysis deletion
- security section in reports

## v1.0 — Production-quality local release

Deliver:

- XLSX support
- complete detector catalogue
- privacy redaction
- deterministic and AI evaluation
- security hardening
- accessibility
- browser matrix
- performance benchmarks
- SBOM and license checks
- production documentation
- release artifacts

Production definition:

- local-first
- single instance
- Docker
- optional local Ollama
- no paid inference API
- no public hosting requirement

## Post-v1 deployment track

Public hosting is a separate decision after v1.

Before approval, evaluate:

- actual portfolio value
- hosting cost
- abuse controls
- anonymous data handling
- retention
- rate limiting
- live versus precomputed AI
- operational ownership
- monitoring
- legal and privacy notices
