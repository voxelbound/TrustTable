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

> **Annotation (2026-09-16, `docs/decision-log.md` D-034):** the human
> decision gate above is now partially resolved — model family/exact
> model (Qwen3.5-4B) and the baseline hardware-tier default are
> decided (Q4_K_M is recorded as the selected quantization because it
> is what the selected model was evaluated at; no comparative
> quantization study was performed). Runtime (`llama.cpp` vs. Ollama)
> and the accelerated hardware-tier default remain open; the real
> local-inference provider still must not start until both are
> resolved.

> **Annotation (2026-09-16, `docs/decision-log.md` D-035):** the human
> decision gate above is now **complete for v0.2 baseline scope**.
> `llama.cpp` is selected as the runtime (Ollama recorded as a future
> alternative, not disqualified). The real local-inference provider is
> now ready to start, scoped to the baseline/CPU-oriented profile
> (Qwen3.5-4B-Q4_K_M on `llama.cpp`). The accelerated hardware-tier
> default remains explicitly deferred, by deliberate choice, as a
> later, non-blocking follow-on.

> **Annotation (2026-09-17, `docs/decision-log.md` D-036):** `llama.cpp`'s
> `llama-server` is hardened as inference infrastructure only — its
> built-in Web UI is disabled in the documented/supported runtime
> profile, and the documented local baseline moves to host port `8081`,
> distinct from TrustTable's own frontend port `8080`. Tracked as
> `AI-07` in `docs/implementation-backlog.md`, sequenced immediately
> after `API-02` and before `AI-05` (`D-033`'s sequencing amendment).
> Does not reopen `D-034`/`D-035`.

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
- optional local AI runtime (specific runtime open — see `docs/decision-log.md` D-007, D-033)
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
