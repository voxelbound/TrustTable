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

Deliver:

- provider abstraction
- disabled and mock providers
- Ollama provider
- deterministic context hypotheses
- validated context inference
- guided questions
- grounded explanations
- prompt-injection trust boundary
- local-model documentation

> **Annotation (2026-09-13, does not edit the list above):** the
> `v0.2 — Local AI beta` design session (`CHG-002`) reopened the
> specific local runtime choice — `llama.cpp` and Ollama remain live
> finalists pending a TrustTable-specific benchmark (see
> `docs/decision-log.md` D-030–D-032, and D-007's appended review
> note). The "Ollama provider" bullet above is stale relative to that
> open decision and may be revised once a runtime is actually chosen;
> it is left unedited here pending that decision, per this project's
> historical-truth convention.

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
