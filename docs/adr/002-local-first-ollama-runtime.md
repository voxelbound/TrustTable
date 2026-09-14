# ADR 002: Local-First Ollama Runtime

**Status:** Under review (2026-09-14) — see review note below.

> **Review note (2026-09-14, `CHG-003` documentation-consistency
> alignment):** this ADR's original decision — Ollama as the default
> live LLM runtime — is under review as of 2026-09-13 and must not be
> treated as current architecture. The `v0.2 — Local AI beta` design
> session (`docs/decision-log.md` `D-007`'s appended review note,
> `D-030`–`D-033`) reopened the specific runtime choice: `llama.cpp`
> and Ollama remain two live finalists, pending a TrustTable-specific
> hands-on benchmark (`AI-06`) and a human decision gate. The original
> decision, rationale, and consequences below are preserved unedited as
> the historical record of what was originally decided; they are not
> current fact until the runtime decision is actually re-recorded (as a
> new ADR revision, or a superseding ADR).

## Decision

Ollama is the default live LLM runtime. It runs on the host, outside the main Docker stack.

Required providers:

- disabled
- mock
- Ollama

## Rationale

- no paid API
- simpler GPU access
- explicit privacy boundary
- test suite does not require a model

## Consequences

- users install Ollama separately for live AI
- Docker-to-host networking must be documented
- AI is optional
