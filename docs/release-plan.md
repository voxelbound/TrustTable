# TrustTable Release Plan

This document states what each milestone delivers and where it stands. It is the planning view at milestone level: per-item status is in `docs/implementation-backlog.md`, the chronology of what was delivered and when is in `docs/delivery-history.md`, and the reasoning behind every change is in `docs/decision-log.md`. Earlier wording that has since been superseded is preserved in this repository's Git history, not repeated here.

## Milestone status

| Milestone | Status |
|---|---|
| v0.1 — Deterministic vertical slice | Complete |
| v0.1.1 — Investigation UX | Complete |
| v0.2 — Local AI beta | Complete; `v0.2.0` published and verified |
| v0.3 — Complete manager workflow | Complete; `v0.3.0` published and verified |
| v1.0 — Production-quality local release | Current milestone, in progress |
| Post-v1 deployment track | Not decided |

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

Status: **complete.**

## v0.1.1 — Investigation UX

Deliver:

- row context for row-anchored findings

No LLM required. Does not change v0.2's scope.

Status: **complete.**

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

Status: **complete.** `v0.2.0` is published to GHCR and was started on a clean Linux host with no GHCR credentials and AI off. The decision gate selected `llama.cpp` and Qwen3.5-4B at Q4_K_M as the baseline (`docs/decision-log.md` D-034, D-035). The local-AI hardware/performance qualification was **waived** by the owner (D-044): it is not a pass, and nothing about minimum, recommended or baseline-tier hardware may be inferred. The images are unsigned, with no attestations or container scan.

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

Status: **complete.** Every feature above is implemented, and `REL-03` is complete (D-049). `v0.3.0` is published and was verified on a clean host with AI off (one pull, start and health check). The images are unsigned, unattested and not container-scanned, and the local-AI setup was not exercised there. The project owner has recorded the `v0.2` and `v0.3` milestones complete, each at the agreed scoped qualification level; `v0.2.0` and `v0.3.0` are the published releases.

## v1.0 — Production-quality local release

Deliver:

- XLSX support
- complete detector catalogue (met only in a narrowed sense; see "Detector catalogue boundary" below)
- privacy redaction
- deterministic and AI evaluation
- security hardening
- accessibility
- browser matrix
- performance benchmarks
- SBOM and license checks
- production documentation
- release artifacts

Status: **in progress.** `v1.0` is the current milestone.

| Deliverable | Status |
|---|---|
| XLSX support | Complete (`ING-03` is complete; D-052, D-053) |
| Complete detector catalogue (narrowed to the Core catalogue) | Closed as the Core catalogue only (`DET-03`, D-065): 26 detectors covering 28 of 41 catalogue entries; 13 carried by named successors |
| UI/UX redesign (`UX-01`) | Slices `UX-02` to `UX-09` implemented and merged; **outcome rejected by the human owner** (see below) |
| Privacy redaction (`PRIV-01`) | Planned; the next planned roadmap item |
| Deterministic and AI evaluation (`EVAL-01`, `EVAL-02`) | Planned |
| Security hardening (`SEC-01`), performance benchmarks (`PERF-01`), accessibility (`A11Y-01`), browser matrix (`BROWSER-01`) | Partly done: `v0.1`-scoped baselines only; full scope open |
| Migration and recovery tests (`MIG-01`) | Planned |
| Production documentation (`DOC-01`) | Planned |
| Release artifacts and the `v1.0` release (`REL-04`) | Planned; blocked unless all requirements in `docs/testing-strategy.md` pass |

### Outcome gate: UI/UX redesign (`UX-01`)

The redesign slices are implemented and merged. After manual end-to-end testing, the human owner rejected the resulting UI/UX outcome as not meeting the intended business-application quality. The implementation is complete, the `UX-01` outcome is not accepted, and substantial redesign is required before it can be. **No replacement design or redesign direction is approved yet.** The sequencing of accessibility, browser-matrix and performance work relative to the redesign is not decided.

### Detector catalogue boundary and unplaced successors

By owner decision (D-061) the "complete detector catalogue" deliverable is the **Core detector catalogue closure**: `DET-03` is closed as **26 detectors covering 28 of 41 catalogue entries; 13 carried by named successors** (D-065). The 41-entry mapping is in `docs/detector-framework.md` §16. The 13 carried entries are not built, not claimed delivered and not `v1.0` scope. Their successor items (`DET-04`, `CCX-01`, `CCX-02`, `DET-05`, `DET-06`, `STD-01`, `HARM-01`, `RULE-03`, with `OBS-02` and `ING-04` also carried out of `DET-03`) are planned with **no milestone placement**, which remains an open owner decision. Still open and undecided: the two `CCX-01` decisions (what counts as a conflicting confirmation, and how a withdrawn relationship is gated) and whether `structural.empty_column` should skip a zero-row dataset (D-062 item 9). Most context-bound detectors stay inactive until a confirmation path ships; the standing principle that column names never define business meaning is partly unmet by the shipped name-based detectors until they migrate, and that exit condition is carried by `DET-05`.

### Open design tracks

The Local AI managed-provisioning architecture (`LAI-01`), a Rules and Expectations design track (`RULE-04`) and file-reading options (`ING-05`) are open, unapproved design tracks with no milestone placement. Nothing is removed from `v1.0` by any of them.

### Production definition

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
