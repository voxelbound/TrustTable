# TrustTable Decision Log

This log summarizes major product and technical decisions. Detailed architecture decisions are stored in `docs/adr/`.

## D-001 — Product direction

**Decision:** Build an AI-assisted data quality investigator for business managers.

**Reason:** Clear business value, personal usefulness, visible AI engineering, and manageable scope.

## D-002 — Primary dataset domain

**Decision:** Use sales transactions as the first demonstration domain.

**Reason:** Understandable business impact and strong cross-field checks.

## D-003 — Primary user

**Decision:** Optimize for business managers, with analysts and engineers as secondary users.

**Impact:** Business conclusions appear before technical metrics.

## D-004 — Workflow

**Decision:** Use:

```text
Upload → Understand → Analyze → Review → Export
```

## D-005 — Deterministic/AI separation

**Decision:** Code calculates facts; AI interprets.

**Impact:** All factual claims require evidence.

## D-006 — Complete AI-disabled mode

**Decision:** TrustTable remains functional without a model.

**Reason:** Reliability, testability, accessibility, and no paid dependency.

## D-007 — Local LLM runtime

**Decision:** Use optional host-installed Ollama.

**Reason:** No token-based API subscription and simpler GPU access.

## D-008 — Public hosted demo

**Decision:** Defer public hosting until after v1.

**Reason:** Focus on local product quality before cost, abuse, retention, and operational concerns.

## D-009 — Version 1 production boundary

**Decision:** Local-first, single-instance product.

**Excluded:** Multi-tenancy, authentication, SaaS operations, public inference SLA.

## D-010 — Backend technology

**Decision:** Python, FastAPI, Pydantic, SQLAlchemy 2, Alembic, SQLite.

## D-011 — Background work

**Decision:** Bounded in-process workers.

**Rejected for v1:** Redis and Celery.

## D-012 — Frontend technology

**Decision:** React, strict TypeScript, Vite, React Router Data Mode, TanStack Query, React Hook Form, Tailwind, generated OpenAPI types.

## D-013 — Client state

**Decision:** No Redux or Zustand in v1.

**State ownership:** server, URL, forms, and local component state.

## D-014 — API contract

**Decision:** Version under `/api/v1`; FastAPI OpenAPI is the generated contract source.

## D-015 — Prompt injection

**Decision:** Make prompt-injection risk detection and mitigation a visible product capability.

**Required test:** Dataset value attempts to instruct the model to claim the dataset is perfect.

## D-016 — Sample transmission

**Decision:** Disabled by default.

**When enabled:** redact, truncate, and isolate samples as untrusted data.

## D-017 — Deterministic authority

**Decision:** The LLM cannot remove findings or alter risk scores.

## D-018 — Persistence

**Decision:** Completed analyses survive restart. Interrupted active jobs fail safely and can be retried.

## D-019 — Data deletion

**Decision:** Users can delete analyses and all derived artifacts.

## D-020 — Original data mutation

**Decision:** No automatic repair or overwrite in v1.

## D-021 — File support

**Decision:** CSV and XLSX; reject macro-enabled files.

## D-022 — Testing standard

**Decision:** Release gates cover unit, integration, end-to-end, accessibility, browser, security, migration, deterministic evaluation, and AI grounding tests.

## D-023 — Repository role handbooks

**Decision:** Define project responsibility roles for human and coding-agent reviews without pretending a fictional team exists.

## D-024 — Engineering review records

**Decision:** Store structured review records rather than fictional meeting minutes.
