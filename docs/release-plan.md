# TrustTable Release Plan

This document states what each milestone delivers and its current status. It is the
planning view, not a progress log: per-item status is in
`docs/implementation-backlog.md`, and the reasoning and history behind every change are in
`docs/decision-log.md`. Earlier wording that has since been superseded is preserved in this
repository's Git history, not repeated here.

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

Current status: **complete.** This is the first promoted portfolio release.

- **Decision gate.** Complete for the baseline scope. `llama.cpp` is the selected runtime
  (Ollama is a future alternative, not disqualified) and Qwen3.5-4B at Q4_K_M is the selected
  baseline model; Q4_K_M is recorded because it is what the model was evaluated at, and no
  comparative quantization study was performed. The accelerated hardware-tier default was
  deliberately deferred as a later, non-blocking follow-on (D-034, D-035; see also D-007's
  appended review note and D-030–D-032).
- **Runtime hardening.** `llama-server` is inference infrastructure only: its built-in Web UI
  is disabled in the supported profile and the local baseline uses host port `8081`, distinct
  from the frontend port `8080` (`AI-07`, D-036), sequenced after `API-02` and before `AI-05`.
- **Grounded AI analysis.** `AI-08` (grounded, advisory per-finding analysis, deployable
  local-AI experience and first-class Linux documentation) was inserted before `REL-02` by
  explicit product direction (D-040). It adds no `v0.3` scope: no rule engine, rule execution,
  persistent review or export.
- **Release.** `REL-02` was delivered in three ordered steps (D-041): the repository-side
  pull-only Compose file and tag-gated publish workflow, the local-AI qualification, and the
  protected publish with a clean-host check. The local-AI qualification was **waived** by the
  owner (D-044): it is not a pass, no real-model benchmark of that path was completed, and
  nothing about minimum, recommended or baseline-tier hardware may be inferred. `v0.2.0` is
  published to GHCR and was started on a clean Linux host with no GHCR credentials and AI off
  (D-045); `REL-02`, the last `v0.2` item, is complete. Live local-AI evaluation is optional in
  `docs/testing-strategy.md` §8, so the release gates are unaffected.

Provenance of the list wording: it reads "real local-inference provider" rather than the
earlier "Ollama provider" wording, and includes the benchmark-harness and decision-gate
entries sequenced ahead of it (D-032, D-033). The earlier wording is preserved in Git history.

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

Current status: **complete.** Every feature above is implemented. `v0.3.0` is published and
was verified on a clean host with AI off (one pull, start and health check), and `REL-03` is
complete (D-049). The images are unsigned, unattested and not container-scanned, and the
local-AI setup was not exercised there. The project owner has recorded the `v0.2` and `v0.3`
milestones complete, each at the agreed scoped qualification level; `v0.2.0` and `v0.3.0` are
the published releases.

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

Current status: **in progress.** `v1.0` is the current milestone.

- **XLSX support — complete.** `ING-03` is complete: Excel upload works from the API and the
  Start screen, and the documented limit settings are read on every parse (D-052, D-053).
- **"Complete detector catalogue" — met only in a narrowed sense.** By owner decision (D-061)
  this bullet is the **Core detector catalogue closure**, and `DET-03` is the Core detector
  catalogue. `DET-03` is closed as **26 detectors covering 28 of 41 catalogue entries; 13
  carried by named successors** (D-065); the 41-entry mapping is in
  `docs/detector-framework.md` §16. The 13 carried entries are not built, not claimed delivered and not `v1.0` scope; their successor items (`DET-04`,
  `CCX-01`, `CCX-02`, `DET-05`, `DET-06`, `STD-01`, `HARM-01`, `RULE-03`, with `OBS-02` and
  `ING-04` also carried out of `DET-03`) are planned with **no milestone placement**, which
  remains an open owner decision. Still open and undecided: the two `CCX-01` decisions (what
  counts as a conflicting confirmation, and how a withdrawn relationship is gated) and whether
  `structural.empty_column` should skip a zero-row dataset (D-062 item 9).
- **How `DET-03` was built** (details in the decision log and the backlog):
  - The detector slices added `completeness.fully_empty_rows`,
    `consistency.inconsistent_booleans`, `validity.implausibly_old_dates`,
    `validity.invalid_email_shape`, `consistency.numeric_values_stored_as_text`,
    `consistency.near_duplicate_categories` and
    `structural.duplicate_normalized_column_name` (D-054, D-055, D-056, D-058).
  - The confirmed design outcome moved two entries out of `DET-03` without dropping or counting
    them as completed: geographic validation (to the proposed standards policy and semantic
    category harmonization capabilities) and the status/date conflict check (to a named
    business-rule follow-up) (D-057).
  - The confirmed-relationship foundation (D-059, D-060) is delivered history under `DET-03`
    and is recorded as package 1 of `CCX-01`; the confirmed-context execution work left
    `DET-03` (D-061).
  - The four closure packages added `structural.empty_dataset`, `structural.unnamed_column` and
    `structural.excessive_parse_failures` (D-062), the minimal Observation foundation with
    `structural.mixed_types`, `consistency.inconsistent_date_formats` and
    `completeness.concentrated_missingness` (D-063), the exfiltration-instruction and
    secret-request evidence subtypes of the existing
    `security.possible_llm_prompt_injection` detector, which added no detector (D-064), and the
    executable catalogue-status check with the closure report (D-065).
  - Most context-bound detectors stay inactive until a confirmation path ships. The standing
    principle that column names never define business meaning is partly unmet by the shipped
    name-based detectors (`line_total_mismatch`, `invalid_percentages`, and the review of
    `invalid_email_shape`) until they migrate; their exit condition is open and is carried by
    `DET-05`.
- **UI/UX redesign — slice S1 built; every other slice planned and not built.** An
  owner-confirmed PLAN CHANGE makes the UI/UX redesign (`UX-01`, slices S1 to S8a) the next
  `v1.0` work, ahead of `DET-04` (D-066). Slice S1, the workspace and a deliberate start
  (`UX-02`, D-068), is built: choosing a file stages it for review and nothing is analyzed
  until Run. Slices S2 to S8a (`UX-03` to `UX-09`) are not built and not authorized. It does not place `DET-04`, `CCX-01`,
  `CCX-02`, `DET-05`, `DET-06`, `OBS-02`, `ING-04`, `STD-01`, `HARM-01` or `RULE-03` in any
  milestone, and nothing is removed from `v1.0`. The sequencing of accessibility,
  browser-matrix and performance work relative to the redesign is not decided. The Local AI
  managed-provisioning architecture (S8b, `LAI-01`), a Rules and Expectations design track
  (`RULE-04`) and file-reading options (`ING-05`) are open, unapproved design tracks with no
  milestone placement. D-067 records the visible supersession of the machine-specific hardware
  wording in D-029 and the `AI-06` screening record.
- **Not yet done.** The rest of the list above is planned or has a `v0.1`-scoped baseline only.

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
