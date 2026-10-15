# Delivery history

This document preserves the delivery chronology that the `README.md` previously carried: what each completed milestone and backlog item delivered, in the words recorded when it was delivered. It is **history, not current behavior**. For what the product does today read the [README](../README.md) and the specifications under `docs/`; for what is still planned read the [implementation backlog](implementation-backlog.md) and the [release plan](release-plan.md). Decisions are recorded in the [decision log](decision-log.md) and are not rewritten here.

Statements below are dated by the point at which they were written. Where a bullet says "at the time this package merged", the later state is stated in the current-state documents, not here.

## Completed milestones

**v0.1 — Deterministic vertical slice: complete and recorded release-ready.** Every bullet in `docs/release-plan.md`'s v0.1 checklist is implemented and tested; all three release-qualification areas (performance evidence, security qualification, release-candidate testing) have real, scoped-baseline evidence; the human owner recorded v0.1 milestone-complete/release-ready. This does **not** itself constitute full `docs/testing-strategy.md` §8 release-candidate CI-gate compliance: the full multi-browser/viewport matrix, SBOM/container scan/license check, full deterministic/AI evaluation, and migration tests remain open, mostly scoped to the later v1.0 milestone.

**v0.1.1 — Investigation UX: complete.** `FIND-01` (row context for row-anchored findings) — this milestone's sole planned deliverable — is implemented in full: the row-context API endpoint, and a Finding Detail UI section with expand and Prev/Next navigation across the affected rows a finding names (see "Delivered work" below).

**v0.2 — Local AI beta: complete, released as `v0.2.0`.** The owner recorded the milestone complete at the agreed scoped qualification level (details below).

**v0.3 — Complete manager workflow: complete, released as `v0.3.0`.** The owner recorded the milestone complete at the agreed scoped qualification level; every `v0.3` backlog item is delivered.

- **Delivered:** `DB-01` — durable SQLAlchemy 2 + Alembic persistence for the Analysis aggregate, replacing the in-memory store; `JOB-01` (complete) — a bounded in-process background worker pool with real cooperative cancellation and a retry endpoint, replacing synchronous in-request pipeline execution; `REM-01` (complete) — structured remediation recommendations with risk warnings, replacing the earlier bare-string advisory steps; `RULE-01` (complete) — a real, persisted validation-rule engine for all 11 rule types; `RULE-02` (complete) — rule generation from findings: 10 of 13 detector categories deterministic (slices 1 and 3), 1 AI-assisted (slice 2, `consistency.inconsistent_capitalization`), and 2 permanently excluded for a stated structural reason; `REV-01` (complete) — persisted per-finding review state, note, and dismissal reason (see "Delivered work" below).
- **Manager UI (`UI-03`, complete):** analysis lifecycle controls (cancel, retry, delete), report generation and download, the rules screen with JSON/YAML export downloads, finding review controls, and a read-only Technical page (profile, sampled or full-data label, timing, detectors and versions). Rule parameter editing and findings filtering by review state need backend routes that do not exist yet.
- **Release (`REL-03`, complete):** the backend version is `0.3.0`, and one acceptance test drives a CSV through the complete persisted workflow — analysis, findings, a finding review, a rule that is created and run, the rules export, a stored Markdown report, a restart, and permanent deletion. **`v0.3.0` is published** (tag `v0.3.0`, both `0.3.0` images on GHCR) and was verified on a clean Linux host with no GHCR credentials: a pull, start and health check with AI off (`docs/decision-log.md` D-049). The images are unsigned, unattested and not container-scanned, and the local-AI setup was not exercised on that host.
- **Remaining for `v0.3`:** nothing. Limits stated at completion: the multi-browser matrix, keyboard accessibility path, SBOM and container scan remain `v1.0` items; the local-AI setup was not exercised on the clean host; and the published images are unsigned, unattested and not container-scanned.

**v0.2 — Local AI beta (released as `v0.2.0`).**

- **Status:** every planned `v0.2` feature is implemented and released as **`v0.2.0`**. Both images are published to GHCR (`ghcr.io/voxelbound/trusttable-backend:0.2.0` and `ghcr.io/voxelbound/trusttable-frontend:0.2.0`), the release workflow's credential-free pull-and-start check passed, and a clean Linux host with no GHCR credentials pulled and started the release with AI off (`docs/decision-log.md` D-045). `Settings.llm_provider` still defaults to `"disabled"`, so every AI capability degrades gracefully to the built-in guidance.
- **Remaining for `v0.2`:** nothing planned; `REL-02`, the last item, is complete.
- **Waived:** the `REL-02` local-AI hardware/performance qualification. No real-model benchmark was completed, it is not a pass, and no minimum, recommended or hardware-tier claim is made (`docs/decision-log.md` D-044).
- **Not covered by the release verification:** the local-AI setup with a real model, the demo analysis, and any host other than Linux x86-64 were not exercised on the clean host; the published images are unsigned, with no attestations or container scan.
- **Release qualification:** scoped-baseline evidence for release-candidate testing, security and performance, as for v0.1 — the existing suites re-run, the new surfaces mapped to the threat model, and the existing performance gate re-run. The multi-browser matrix, keyboard checks, full deterministic evaluation and the SBOM, container-scan and license checks remain open, mostly scoped to `v1.0`.
- **What `v0.2` adds** (detail under "Delivered work" below):
  - the model/runtime decision gate is closed — Qwen3.5-4B-Q4_K_M on `llama.cpp`, baseline/CPU-oriented profile (`docs/decision-log.md` D-034/D-035); this names a software configuration, not a hardware requirement;
  - the AI provider interface and its three providers (disabled, mock, real `llama.cpp`), the local-AI benchmark harness with its earlier hands-on model evaluation, and the finding-analysis qualification harness (D-043);
  - deterministic and AI-assisted context inference (`CTX-01`–`CTX-03`), the Context confirmation service (`API-02`) and `llama-server` runtime hardening (`AI-07`);
  - a two-phase context/AI architecture (D-037): the deterministic pipeline stays unchanged and unattended, and context confirmation and AI interpretation are a second, optional, additive enrichment phase over an already-completed analysis;
  - the Context and AI UI (`UI-02`): grounded finding explanations and the Context screen (editable fields with provenance, guided questions, confirm/finalize);
  - the prompt-injection adversarial evaluation (`EVAL-AI-01`, D-039): a compromised-model evaluation against the real routes proved an adversarial response cannot become an accepted AI interpretation that calls the dataset perfect or tells the user to disregard findings, and closed a real validator gap it found;
  - AI-assisted finding analysis (`AI-08`, D-040): four grounded, advisory sections per finding from one structured, validated model response — or built-in guidance when AI is off or its answer is rejected.

## Delivered work

**Foundation**

- **FND-01** — repository foundation: runnable backend/frontend skeleton, Docker Compose baseline.
- **FND-02** — typed configuration from `.env.example`.
- **FND-03** — continuous integration (formatting, lint, types, tests, dependency scan).
- **FND-04** — structured API errors and request IDs.
- **FND-05** — OpenAPI-generated frontend contract pipeline, with a CI drift check.

**v0.1 — Deterministic vertical slice**

- **DEMO-01** — synthetic sales-demo generator (deterministic, 13 injected issue types).
- **ING-01 / ING-02** — parsing contracts and a secure CSV parser.
- **PROF-01 / PROF-02 / PROF-03** — profiling schemas, type inference, and core profiling metrics.
- **DET-01 / DET-02** — the detector interface and the full initial detector set (all 12 deterministic detectors: duplicate rows, empty columns, excessive missing values, missing likely identifiers, inconsistent capitalization, leading/trailing whitespace, future dates, negative measures, invalid percentages, line-total mismatch, suspiciously constant columns, extreme outliers).
- **SEC-02** — the LLM input/output trust boundary (untrusted-data envelope, safe prompt builder, model-output validator); no real LLM provider was wired in when this package merged (one is since `AI-03`).
- **DET-SEC-01** — the prompt-injection risk detector (`security.possible_llm_prompt_injection`), bringing the then-current detector set to 13 (the catalogue has since grown; see `DET-03` under "Project status" in the README).
- **RISK-01** — deterministic risk scoring: per-finding priority scores and a four-label dataset trust assessment, computed with no AI/LLM input path at all.
- **API-01** — the analysis API: an in-memory orchestration engine (parsing → profiling → detection → scoring) exposed over real `/api/v1` HTTP routes — `POST /demo/sales`, `GET /analyses/{id}`, `.../status`, `.../profile`, `.../findings`, `.../findings/{finding_id}`, `.../findings/{finding_id}/evidence`, `POST .../cancel`.
- **UI-01** — the basic investigation UI, complete: a Start screen (sales-demo action plus generic CSV upload), a named-stage progress view, an Overview screen (trust assessment, top findings, dataset summary), a Findings list (severity/category/search filtering), a Finding detail screen (evidence, representative examples, technical metadata, and — at the time this package merged — honestly-disclosed not-yet-available business-impact/remediation/validation-rule/review sections; the first three are now real, see `AI-08` below), and a dedicated prompt-injection-warning presentation for `ai_processing_security` findings.
- **REL-01** (scoped) — Docker Compose production-configuration hardening: both services now restart automatically after an unexpected exit; SBOM generation and container image scanning are explicitly deferred to `SEC-01`'s later, full scope.
- **API-01, extending** — generic CSV file-upload analysis creation (`POST /api/v1/analyses`, CSV only, with extension/size validation and filename sanitization; `.xlsx` was then still `ING-03`, a later backlog item; see "Project status" in the README for Excel today) — completing every remaining `docs/release-plan.md` v0.1 checklist item.

**v0.1 release-qualification (scoped baselines)**

- **PERF-01** (v0.1-scoped) — a performance baseline across 10k/100k/250k-row and one wide-column synthetic case; full v1.0-scale benchmarking and tuning remain open.
- **SEC-01** (v0.1-scoped) — a security-qualification review closing a logging-safety test gap and adding an unsafe-HTML-rendering regression guard; SBOM generation, container scanning, and license checking remain `SEC-01`'s later, full scope.
- **BROWSER-01 / A11Y-01** (v0.1-scoped) — release-candidate testing qualification: the first live execution of the Chromium/axe-core browser-accessibility suite against the real Docker Compose stack (6/6 tests passing); the full multi-browser/viewport matrix and full accessibility suite remain open, later v1.0-milestone scope.

**v0.1.1 — Investigation UX (complete)**

- **FIND-01** — row context for row-anchored findings: `GET /api/v1/analyses/{id}/findings/{finding_id}/row-context` returns a bounded (max 25 rows per side) physical-neighborhood window around one of a finding's own affected rows, reconstructed on demand from the analysis's retained upload bytes (never a standing `ParsedDataset`); the Finding Detail screen's new "Row context" section renders it with the anchor row highlighted, an expand control, and, for findings that name more than one affected row, Prev/Next navigation between the named rows (since `UX-06` part a, D-073, the screen for these rows is the data inspector grid). Not `Evidence`, not in Report/export output, never automatic AI-prompt input (`docs/decision-log.md` D-025).

**Local AI beta (v0.2 — complete)**

- **AI-01** — the AI provider interface: a framework-independent contract package (the six model-call operations, request/response/health-check shapes, a provider-error hierarchy, and the `AIProvider` protocol every provider implements against).
- **AI-02** — the two non-real providers required by `docs/product-requirements.md` §12: `DisabledProvider` (`llm_provider=disabled`, `D-006`'s "complete AI-disabled mode") and `MockProvider` (`llm_provider=mock`, configurable static or dynamic output, proven capable of producing and having rejected genuinely adversarial "attempt to follow the injected instruction" output against the real `validate_model_output`), plus a small `create_provider` factory.
- **AI-03** — the real local-inference provider: `LlamaCppProvider` (`llm_provider=llama_cpp`), a real `httpx`-based client for `llama.cpp`'s `llama-server`, reusing `build_safe_prompt` unmodified and never calling `validate_model_output` itself. Registered in the provider factory; `Settings.llm_provider`'s default remains `disabled`. No live-model test runs in CI (deterministic `httpx.MockTransport` tests only, matching the benchmark-only adapter's own precedent). **Updated (`WP-065`, defect fix):** at the time this package merged, no FastAPI route called it yet — that has since changed; see the `UI-02` slices below.
- **AI-06** (harness plus completed hands-on evaluation) — a persistent, config-driven local-AI benchmark harness: six fixed, versioned task fixtures (one per `AIOperation`) grounded in real demo-dataset evidence, and a runner scoring structured-output validity/groundedness, latency, bounded retry rate, and repeated-call consistency for any `AIProvider`. The full hands-on evaluation (six-candidate first-round screening, a blind qualitative comparison, and a controlled performance/resource comparison between the two finalists) is complete and published (`docs/evaluation/ai-06-first-round-model-screening-2026-09-16.md`); the resulting model and runtime decision is recorded in `docs/decision-log.md` D-034/D-035.
- **AI-04** — local runtime documentation: a hands-on setup guide (`docs/local-development.md`) for installing `llama.cpp`'s `llama-server`, manually obtaining and verifying the baseline model (Qwen3.5-4B-Q4_K_M), starting it on the baseline/CPU-oriented profile, and configuring TrustTable's `LLM_PROVIDER`/`LLM_BASE_URL`/`LLM_MODEL` settings to reach it — no paid account required.
- **CTX-01** — deterministic context hypotheses: a framework-independent, AI-free heuristics module (`context_inference/heuristics.py`) that infers candidate keys, business dates, measure/dimension roles, row grain, primary entity, and a narrow disclosed probable-domain guess directly from `PROF-02`/`PROF-03`'s already-computed column facts — no AI/LLM call of any kind. `currency_behavior` and `expected_business_rules` are honestly left unresolved (no deterministic signal exists for either yet).
- **CTX-02** (enabling slice) — validated AI context inference: `context_inference/ai_context.py` calls a real `AIProvider` for `AIOperation.CONTEXT_INFERENCE`, grounded in `CTX-01`'s deterministic context (serialized into the trust boundary's untrusted `confirmed_context`, per the existing architecture) plus optional bounded dataset samples (off by default), validates every response through `SEC-02`'s real `validate_model_output`, retries once with feedback on rejection, and never raises on provider failure. An accepted response becomes one new `probable_domain` hypothesis that wins consolidation over `CTX-01`'s own narrower heuristic. At the time this package merged: not yet wired into `analysis.service`, any `AnalysisState`, or any API route — no product-visible behavior change for any existing analysis; `Analysis.security_exposure` unchanged. **Superseded (`UI-02` slice 2, `WP-064` r2):** `GET .../context` now calls this module's `run_context_inference` on an analysis's first inference (see the `UI-02` slice 2 bullet below) — `Analysis.security_exposure` remains unchanged regardless, and must never be read as reflecting this separate call (`docs/decision-log.md` D-038).
- **CTX-03** (generation only) — guided questions: `context_inference/guided_questions.py` deterministically generates up to five business-language `ClarificationQuestion`s (`docs/domain-model.md` §10), one per `CTX-01`/`CTX-02` context field still unresolved (`probable_domain`, `row_grain`, `primary_entity`, `currency_behavior`, `expected_business_rules`) — never more, by construction, matching the product's own "no more than five" rule exactly. Deliberately deterministic rather than AI-generated, since no structured multi-question output shape exists in this codebase's AI trust boundary yet.
- **API-02** (service-layer enabling slice, no HTTP route at the time) — context confirmation: `analysis/service.py` gains `get_or_infer_context`/`get_guided_questions`/`confirm_context_fields`/`answer_guided_question`/`finalize_context`, plus `ClarificationAnswer` (`docs/domain-model.md` §11, implemented for the first time). This is a strictly additive layer over an already-`COMPLETED` analysis, with optimistic-concurrency versioning (`docs/api-specification.md` §9's "requires resource version"). **`AnalysisState` and `run_analysis` are deliberately unchanged** — wiring the pipeline itself to pause for confirmation would regress the already-shipped `v0.1`/`v0.1.1` UI's poll-until-`COMPLETED` behavior, so that remains an open, later, human-directed product decision. `CTX-02`'s AI augmentation is correspondingly not invoked either. The actual FastAPI HTTP routes for this already-specified contract, live-pipeline wiring for `CTX-01`/`CTX-02`/`CTX-03`, and `UI-02` remain open.
- **AI-07** — `llama-server` runtime hardening: `llama.cpp`'s `llama-server` is treated strictly as inference infrastructure, never a user-facing application — TrustTable is the sole user-facing surface. The documented/supported runtime profile now starts `llama-server` with `--no-webui` on its own dedicated port (`8081`), distinct from TrustTable's own frontend port (`8080`), eliminating a real host-port collision (`docs/decision-log.md` D-036). `LLM_BASE_URL`'s default value and documented example updated to match. Does not reopen `D-034`/`D-035` — the Qwen3.5-4B-Q4_K_M + `llama.cpp` CPU-oriented baseline is unchanged.
- **AI-05** (enabling slice) — grounded finding explanations: a new `domain/explanation.py` `FindingExplanation` value object, `explanation/deterministic.py` (no AI, always available — the first implementation of `docs/product-requirements.md` §5.7's "deterministic explanations" AI-disabled-mode requirement) and `explanation/ai_explanation.py` (calls a real `AIProvider` for `AIOperation.FINDING_EXPLANATION`, grounded in one finding's own captured `Evidence`, validated through `SEC-02`'s existing `validate_model_output` — whose generic schema already structurally enforces every one of `AI-05`'s own backlog rejection rules: unknown evidence, unknown columns, incorrect numbers, and no way to remove a finding or replace its score). At the time this package merged: not yet wired into `analysis.service`, any API route, or the UI. **Superseded (`UI-02` slice 1, see below):** `GET .../findings/{finding_id}/explanation` now calls this module through the API route layer, never `analysis.service` — that module's own no-`ai_boundary`/`ai_provider`-import guarantee and `Analysis.security_exposure` remain unchanged and independent of this call (`docs/decision-log.md` D-038).
- **`UI-02` slice 1** — the first real, user-visible piece of `v0.2`'s AI capability: `GET /api/v1/analyses/{id}/findings/{finding_id}/explanation` always returns `AI-05`'s deterministic explanation, additionally attempting the validated AI path through the real provider factory when `LLM_PROVIDER` is not `disabled` (the default), falling back to the deterministic explanation on rejection or provider error. `FindingExplanation` gains `provider_name`/`model_identifier` (additive, `docs/decision-log.md` D-037's disclosed reconciliation step toward `docs/domain-model.md` §14's `AIInterpretation` shape). The Finding Detail screen's new "Explanation" section displays the narrative, provenance, and model location.
- **`UI-02` slice 2 (completes `UI-02`)** — five new real routes (`GET`/`PUT /analyses/{id}/context`, `GET /analyses/{id}/questions`, `POST .../questions/{question_id}/answer`, `POST /analyses/{id}/finalize`) wiring `API-02`'s already-built, already-tested service methods to HTTP for the first time, plus the real Context screen (`docs/ui-specification.md` §4.4, reachable from Overview): the five editable single-value context fields with a provenance label per field, the four column-role fields shown read-only, the guided-questions list (suggested-answer buttons and free text), and a Finalize action. **Pre-merge correction (`docs/decision-log.md` D-037's appended closure note):** the first version of this package left `CTX-02` and the explanation path structurally disconnected from context confirmation. Corrected before merge — `GET .../context` now calls `CTX-02`'s real validated AI context inference on an analysis's first inference only (never re-invoked once cached), and `GET .../findings/{finding_id}/explanation`'s envelope now carries the finalized `DatasetContext` once `POST .../finalize` has actually been called, making `finalize` the real, observable trigger for context-grounded enrichment. `finalize_context`'s own service-layer behavior (marks context finalized, no synchronous fan-out AI call across every finding) is otherwise unchanged.
- **Defect fix — AI exposure/provenance disclosure semantics (`docs/decision-log.md` D-038, `WP-065`):** the human owner found, via manual end-to-end testing against a real `llama.cpp` runtime, that the Finding Detail screen could show an accepted AI explanation (`"AI interpretation — llama_cpp (...)"`) while simultaneously claiming, via a misleading generic "AI model enabled" row and `PromptInjectionWarning`'s unrelated `security_exposure`-derived fields, that no AI call was made. Both underlying signals were individually correct but had different, un-disclosed scopes (`Analysis.security_exposure` describes only the deterministic pipeline's own, permanently-`False` raw-sample-exposure posture; the explanation route's own AI usage is a separate, independently-configured call). Fixed by a new `FindingExplanationResponse.ai_call_status` field (`not_configured`/`attempted_accepted`/`attempted_rejected`/`attempted_provider_error`), removal of the misleading Technical-metadata row, reworded `PromptInjectionWarning` copy, and corrections to stale documentation (`docs/architecture.md`, `docs/api-specification.md`) that had claimed no route called a provider after `UI-02` had already shipped ones that do. Does not reopen `D-034`/`D-035` — the manual test used `Qwen3.5-9B` locally, not adopted as any baseline change.
- **EVAL-AI-01** — prompt-injection adversarial evaluation: an end-to-end suite (`backend/tests/security/test_prompt_injection_adversarial_evaluation.py`) drives the real routes and provider factory with a compromised model that obeys the injected instruction ("claim this dataset is perfect"), including variants that cite genuine evidence IDs. It found that `SEC-02`'s output validator was purely structural — a schema-valid narrative-only "this dataset is perfect" response would have been accepted and shown as an AI interpretation — so a bounded, closed claim screen was added to it (`docs/decision-log.md` D-039): unsupported whole-dataset claims and instructions to disregard deterministic results are now rejected, and the user sees the deterministic explanation. The evaluation proves findings, evidence, severity and the trust assessment are byte-for-byte unchanged, retry feedback and logs carry reason codes only, honest narratives are still accepted, and the adversarial context-inference path leaves context unchanged. The screen is lexical and evadable by a creative paraphrase — a documented limit, with deterministic authority remaining the guarantee. The Finding Detail protections list states the new protection. Asserting the applied protections in the *exported* report is carried to `v0.3`, when that report exists.
- **AI-08** — grounded AI analysis, recommendations and a deployable local-AI experience. Each finding now has one coherent analysis: an explanation, possible business impact, a remediation suggestion and a proposed validation rule. With a local model these come from one *structured*, constrained response (`finding_analysis_v1`) that is validated role by role — impact statements are presented only as potential impacts with the condition they depend on, labelled conditional or informed by your confirmed context by TrustTable itself (a model cannot award its own text the standing of an established fact); remediation is advisory only and never changes your data; the proposed rule is a proposal, never active. Without AI, or when a model's answer is rejected or fails, the same four sections come from built-in guidance for all 13 detectors, and the deterministic findings, evidence, severity and trust assessment are unchanged either way. Only context you confirmed and finalized is ever sent to a model. The UI shows a readable identity ("Local AI · llama.cpp · Qwen3.5 4B") and never a file path. Linux install and local-AI setup are documented in [`docs/installation-linux.md`](installation-linux.md), and the Docker Compose backend can now reach a host `llama-server` on Linux. The rule engine, rule execution, persistent review and exports remain `v0.3` (`docs/decision-log.md` D-040).
- **REL-02 (complete)** — a pull-only Compose file (`docker-compose.release.yml`) and a tag-gated GHCR publish workflow (`docs/decision-log.md` D-041), the finding-analysis qualification harness (D-043), scoped `v0.2` release qualification and version `0.2.0`, and the published, verified `v0.2.0` release (D-045); see [`docs/release-images.md`](release-images.md). The local-AI hardware/performance qualification was waived (D-044).

**Complete manager workflow (v0.3 — complete)**

- **DB-01** — durable persistence for the Analysis aggregate: SQLAlchemy 2 + Alembic, SQLite (`docs/architecture.md` §8, `ADR-004`). A completed (or in-progress) analysis — dataset metadata, raw content, profile, findings, evidence, context, guided questions, and trust assessment, exactly as `analysis.service.Analysis` already defines it — now survives an application process restart unchanged; an analysis left in a non-terminal state by an unexpected restart is deterministically marked failed the next time the real application starts, rather than staying stuck. Alembic migrations run automatically at startup, and `/health/ready` gained a `storage` check reporting the migration state. `docker-compose.yml`'s backend service gained a named `/data` volume so the database survives container recreation. At the time of this package there was no AI-interpretation/review/rule/report persistence — those domain objects did not exist as implemented code, and the later `v0.3` items added them — and no API response shape changed.
- **JOB-01 (complete)** — a bounded in-process background worker pool (`docs/architecture.md` §9, `ADR-004`), replacing synchronous in-request pipeline execution for the first time. `POST /demo/sales`/`POST /analyses` now return immediately with `state=queued`; the real pipeline runs on a background worker, with real, persisted `parsing`/`profiling`/`detecting` stage progression observable through `GET /status`. Cancelling an in-flight analysis (`POST .../cancel`) now actually stops it cooperatively at the next checkpoint — not only a not-yet-started one, as before. **Slice 2:** `POST /analyses/{id}/retry` retries a `FAILED` analysis by creating a new, independent analysis over the same dataset content — never a versioned attempt reusing the original ID — submitted to the same worker pool; the original analysis is never mutated. `GET /status` now reports `retryable` (`true` only when `failed`).
- **REM-01 (complete)** — structured remediation options with risk warnings (`docs/domain-model.md` §16), reconciling `AI-05`'s disclosed narrower interim shape. Each finding's remediation is now 1-3 structured recommendations — who should act, how urgently, how to correct rows already affected, how to prevent recurrence at the source, an always-populated risk warning, a verification step and an optional technical example — grounded in the finding's own evidence when AI-generated (`finding_analysis_v2`), and authored for all 13 detectors when AI is off, rejected or fails. Advisory only; TrustTable still never changes uploaded data. No persistence change: remediation stays a per-request computation, as it was after `AI-08`.
- **RULE-01 (complete)** — a real, persisted validation-rule engine (`docs/domain-model.md` §18-19) for all 11 `docs/product-requirements.md` §13 rule types: `not_null`, `unique`, `accepted_values`, `numeric_range`, `date_range`, `regex`, `max_missing_percentage`, `max_duplicate_percentage`, `approximate_equality` (slice 1), plus `expression_comparison`/`conditional_rule` (slice 2) — numeric-only, structured-parameter comparisons (a closed `ComparisonOperator` set; no expression grammar, no `eval`/`exec`). A rule executes immediately on creation, and again on demand, against the analysis's real current rows — never a sample — producing exact pass/fail/skipped counts and bounded example failures, and persists with the analysis. Rule generation from findings (`RULE-02`, now complete, below) and the manager-facing UI (`UI-03`) remain the rest of `v0.3`.
- **RULE-02 (slice 1)** — deterministic rule generation from findings: `GET .../findings/{finding_id}/rule-proposal` builds and executes a real candidate `ValidationRule` for 9 of 13 detector categories, with every parameter read verbatim from the finding's own already-computed evidence — never a new calculation, never AI — and returns it unpersisted for review. Accepting the offer is a normal `POST .../rules` call (now finding-aware), which records `provenance: "detector_generated"`. The remaining 4 categories, most notably `cross_field.line_total_mismatch` (whose real check is multiplicative, not the additive comparison `approximate_equality` performs), have no safe deterministic mapping and are excluded rather than offered incorrectly.
- **RULE-02 (slice 2)** — AI-assisted rule generation for one of those 4 excluded categories, `consistency.inconsistent_capitalization`: its own evidence already lists every casing actually observed for one value, so the only remaining judgment is which is canonical. When a real AI provider is configured, `GET .../rule-proposal` asks it to choose — a closed, per-request contract that can only select one of the finding's own exact observed values, never invent one — executes the resulting `accepted_values` rule against real rows, and returns it unpersisted; accepting it records `provenance: "ai_assisted"`. With AI disabled, rejected, or erroring, the response is unchanged from slice 1's honest "no safe proposal" answer. `cross_field.line_total_mismatch` and `security.possible_llm_prompt_injection` stay excluded even with AI, for the same rule-type/regex-length reasons as slice 1 — no amount of AI choice repairs a rule-type mismatch.
- **RULE-02 (slice 3, `RULE-02` now complete)** — deterministic rule generation for the last safely-mappable category, `statistical.suspiciously_constant_column`: unlike `consistency.inconsistent_capitalization`, a constant column has exactly one observed value (`distinct_count == 1`), so there is no canonical-choice judgment to make and this stays deterministic, never AI. The detector now captures that verbatim value; `GET .../rule-proposal` offers a real, executed `accepted_values` candidate for it, and accepting it records `provenance: "detector_generated"`, identical to slice 1's other 9 categories. Every one of `RULE-02`'s 13 detector categories now has a final outcome: 10 deterministic, 1 AI-assisted, and 2 (`cross_field.line_total_mismatch`, `security.possible_llm_prompt_injection`) permanently excluded for the structural reason stated above. (The manager-facing UI, `UI-03`, followed in this milestone.)
- **REV-01 (complete)** — persisted per-finding review state (`docs/domain-model.md` §12, `docs/product-requirements.md` §8.6: `unreviewed`/`confirmed`/`dismissed`/`needs_investigation`), an optional note, and a dismissal reason, required exactly when dismissing. `PUT /analyses/{id}/findings/{finding_id}/review` sets it immediately and persists across a restart; `GET .../findings`/`GET .../findings/{finding_id}` both now report it, defaulting to unreviewed with no note for a finding never reviewed. The deterministic finding itself is never mutated by a review — they're stored separately. (The manager-facing UI, `UI-03`, followed in this milestone.)

**Production-quality local release (v1.0 — begun)**

- **ING-03 (complete)** — secure Excel support in four slices: a standard-library `.xlsx` parser that never evaluates formulas, refuses macro-enabled, encrypted and malformed workbooks and bounds decompression by counting the bytes it reads; upload through `POST /api/v1/analyses` with an optional `worksheet` field, refusal before any analysis exists, and every pipeline stage reading the chosen worksheet; the Start screen's file picker with a worksheet chooser, with the Overview and Technical details screens naming the worksheet analyzed; and the documented size, row, column, worksheet and cell limit settings read on every parse (`docs/decision-log.md` D-050 to D-053).
- **DET-03 (closed as the Core detector catalogue)** — detector catalogue, delivered in slices. Slice 1 added `completeness.fully_empty_rows` and `consistency.inconsistent_booleans`, each with evidence and built-in guidance, bringing the catalogue to 15 detectors (`docs/decision-log.md` D-054). Slice 2 added `validity.implausibly_old_dates` and `validity.invalid_email_shape` (counts and row numbers only, never an email value), bringing it to 17 (`docs/decision-log.md` D-055). Slice 3 added `consistency.numeric_values_stored_as_text` and `consistency.near_duplicate_categories`, bringing it to 19 (`docs/decision-log.md` D-056). Slice 4 added `structural.duplicate_normalized_column_name`, bringing it to 20 (`docs/decision-log.md` D-058). A confirmed-relationship foundation (not a detector; the count stays 20) stores user-stated start/end-date relationships with immutable versions behind `POST` and `GET .../confirmed-relationships`, with withdrawal exempt from the version caps (`docs/decision-log.md` D-060). Closure package 1 (D-062) added `structural.empty_dataset`, `structural.unnamed_column` and `structural.excessive_parse_failures`, bringing it to 23. Closure package 2 (D-063) added the minimal Observation foundation, a neutral read-only record behind `GET .../observations`, and three observation-only producers (`structural.mixed_types`, `consistency.inconsistent_date_formats`, `completeness.concentrated_missingness`), bringing it to 26. Closure package 3 (D-064) covers the exfiltration-instruction and secret-request catalogue entries as evidence subtypes of the existing `security.possible_llm_prompt_injection` (version 2), so the count stays 26 and the closure target is amended from 27 to 26 detectors covering 28 of 41 entries. Closure package 4 (D-065) added an executable catalogue-status check and closed `DET-03` as the Core detector catalogue: 26 detectors covering 28 of 41 catalogue entries; 13 carried by named successors, which are planned and not built.

## DET-03 closure record

This section holds the design record, per-package notes, boundaries and completion definition that the implementation backlog's `DET-03` item carried before it was compacted to a current item record. The text is moved unchanged; the current item is in [`implementation-backlog.md`](implementation-backlog.md).

### Detectors built before the closure plan

Each is registered and covered by built-in guidance. The catalogue held 20 detectors after
slice 4.

| Slice | Decision | Detectors | Rule proposal |
|---|---|---|---|
| 1 | D-054 | `completeness.fully_empty_rows`, `consistency.inconsistent_booleans` | none, by design |
| 2 | D-055 | `validity.implausibly_old_dates`, `validity.invalid_email_shape` | the date detector proposes a date-range rule from its own evidence; the email detector proposes none (counts only, never an email value) |
| 3 | D-056 | `consistency.numeric_values_stored_as_text`, `consistency.near_duplicate_categories` | none, by design |
| 4 | D-058 | `structural.duplicate_normalized_column_name` | none, by design |

### Closure packages (all built)

| # | Package | Delivered | Registered after |
|---|---|---|---|
| 0 | Re-scope materialization (documentation only) | The D-061 record | 20 |
| 1 | Structural and ingest closure (D-062) | Zero-row and header-only investigation; `structural.empty_dataset`; an immutable in-memory parser-warning projection limited to four warning codes; `structural.unnamed_column`; `structural.excessive_parse_failures`. No persisted ingest-facts record | 23 |
| 2 | Observation and value-evidence slice (D-063) | The minimal Observation foundation, a read-only API and a read-only results-UI list; `structural.mixed_types`, `consistency.inconsistent_date_formats`, `completeness.concentrated_missingness` | 26 |
| 3 | Security detector slice (D-064) | The adversarial suite extended first; subtypes of the existing detector; bounded, redacted evidence; "possible risk" wording; the Security Reviewer review. Built as subtypes of the existing detector; no detector added, 26 registered (D-064) | 26 |
| 4 | `DET-03` closure (D-065) | An executable catalogue-status check against the 41-entry table; document and count reconciliation; the closure report | 26 |

### Design record that shaped the closure

- **D-057 (design materialization, documentation only).** Two catalogue entries were moved
  out of `DET-03`, not dropped and never counted as completed: "invalid country/region
  values" (carried by the proposed *standards policy* and *semantic category harmonization*
  capabilities) and "status/date conflict" (carried by a named business-rule follow-up).
  Context-free detectors can close independently; context-bound detectors depend on a
  confirmed-context foundation and stay inactive, with contract-level tests, until a
  confirmation path ships. The name-based shipped detectors `cross_field.line_total_mismatch`
  and `validity.invalid_percentages` must migrate to confirmed roles, and
  `validity.invalid_email_shape` is a compatibility exception to review, with a compatibility
  window and a measurable owner-visible exit condition (open; carried by `DET-05`).
- **D-059 (confirmed-context foundation design, documentation only).** The foundation was
  split into two ordered packages and the observation type folded into the second. Package 1,
  the confirmed-relationship foundation, delivers the persisted record (kind
  `start_end_date`) with immutable versions and a stable relationship id, server-set
  provenance, confirm / replace / withdraw with version-aware writes, `POST` and `GET
  .../confirmed-relationships` (current projection plus history), the storage limits and the
  `delete_analysis` cascade; `POST` returns `check_status: "not_active"`, and it does not
  claim context-bound detection is active. It was delivered as `WP-106` (D-060). The second
  package, context-bound execution, was gated on two open decisions (what counts as a
  *conflicting* confirmation; how the gate and summary treat a *withdrawn* relationship) and
  on an open owner question: whether a withdrawal is exempt from the 50-versions-per-relationship
  cap (as decided, a relationship at 50 versions can no longer be replaced or withdrawn, and
  only deleting the analysis recovers it).
- **D-061 (closure boundary, PLAN CHANGE, documentation only).** The owner approved a finite
  closure boundary. The confirmed-context execution engine (the former "package 2": the gate,
  the durable second pass, the scheduler, stale-run recovery, the awaiting-confirmation
  summary and `NOT_CHECKED`) left `DET-03` and became `CCX-01`. **`WP-106` is preserved**: it
  is delivered history under `DET-03` and is recorded as `CCX-01` package 1. The minimal
  Observation foundation ships first, with a value-evidence producer, and `CCX-01` later adds
  `NOT_CHECKED` as a new kind; D-059 items 11 and 15 are superseded on ordering only.

### Closure packages: notes

Packages 1, 2 and 3 were technically independent of each other; package 4 followed all
three. Each had its own acceptance criteria, reviews and evidence.

- **Package 1 (D-062).** The zero-row investigation found that the parsers accept a
  header-only CSV or worksheet, so the empty case is detector-owned and the
  parser-owned alternative no longer applies. The four-code ingest-facts projection is in
  memory, behind a default-off metadata flag. No persisted ingest-facts record,
  Observation, confirmed-context execution, scheduler or `NOT_CHECKED` work was built, and
  no detector reads confirmed relationships.
- **Package 2 (D-063).** The Observation is a neutral record with no severity, confidence or
  priority and one closed kind (`value_evidence`), stored in a new nullable
  `observations_json` column (migration `0008`), read through the read-only
  `GET /api/v1/analyses/{analysis_id}/observations` route and listed read-only on the
  Overview screen. A negative allowlist test fails if an Observation field reaches score,
  priority, an AI payload, an export or a report.
- **Package 3 (D-064).** By owner decision SD-989e7edf3d5a (option R), catalogue entries 40
  (possible data-exfiltration instruction) and 41 (suspicious secret-request text) are
  covered as **evidence subtypes of the existing
  `security.possible_llm_prompt_injection`** (version 2) instead of a second detector, which
  amended the closure target from 27 to 26 registered detectors covering the same 28 of 41
  entries. Built: a closed subtype vocabulary and per-subtype row counts in the evidence,
  extended phrasings for the two heightened families, invisible-character and compatibility
  normalization, bounded redacted evidence (never text after a secret or exfiltration
  request), an extended adversarial suite and a recorded Security Reviewer approval. It is
  still one finding per column; identity, severity and trust-score effect are unchanged for
  every column in which nothing newly recognised appears, and newly recognised phrasings
  count wherever they appear, so a column version 1 already flagged can rise in severity and
  priority (owner decision SD-0cc2de8a9889, option A).
- **Package 4 (D-065).** The check (`backend/tests/detectors/test_catalogue_status.py`)
  compares the 41-entry table in `docs/detector-framework.md` section 16 with the real
  registry and with the successor items in the implementation backlog, so a dropped row, an unknown
  detector, an unknown successor or a moved entry counted as built fails the test run. No
  detector, finding, score, API or UI behavior changed in this package.

### Boundaries that held for packages 1 to 3

The parser-warning projection is in memory, limited to `parsing.empty_column_name`,
`parsing.ragged_row`, `parsing.xlsx_formula_without_cached_value` and
`parsing.xlsx_error_value`, carries counts and bounded references and never a message or a
cell value, and reaches detectors through an additive optional input behind a flag that
defaults to off. Observations are neutral, have no severity, confidence or priority, have
one closed kind (`value_evidence`), are never counted by trust scoring or priority, never
enter an AI payload, and are excluded from exports and reports for now. The extension seam
is that a later kind is a new kind, never a change to `value_evidence`. The provisional
Observation API is recorded in the API specification and the domain model. There is no
dismissal, suppression, history, scheduling, `NOT_CHECKED`, scheduler, second-pass
machinery or stale-run recovery in `DET-03`, and **no `DET-03` detector reads confirmed
relationships**.

### Finite COMPLETE definition (met by D-065)

`DET-03` is complete when: (1) the title and scope are reconciled and no document assigns
confirmed context, a scheduler, `NOT_CHECKED`, persisted ingest facts or Observation
workflow to it; (2) the registry holds exactly 26 detectors (27 before D-064) and the
original 20 remain registered and green; (3) empty dataset is terminal, as a registered
detector; (4) unnamed column and excessive parse failures read only the four-code
projection, with nothing persisted or exposed; (5) the three observation detectors are
readable through the API and visible in the results UI, never change score or priority, and
never enter an AI payload; (6) the security coverage exists with an extended adversarial
suite, bounded and redacted evidence and a recorded Security Reviewer approval; (7) the
executable catalogue-status check passes: every one of the 41 entries is built, built by
closure, moved to a named existing successor, or moved previously, and moved entries are
never counted as built; (8) documents are reconciled with the wording "26 detectors
covering 28 of 41 catalogue entries; 13 carried by named successors", never "complete
catalogue built"; (9) CI is green on the final fingerprint with no stale verification and no
unresolved blocking finding; (10) the owner records the item complete.

### Dependency graph as recorded at closure

The implementation backlog now carries only the edges that still concern the planned successor items; the graph as recorded at closure, including the built closure packages, is kept here.

```yaml
dependency_graph_closure:
  schema: 1
  status: design-recorded-not-implemented
  supersedes: [dependency_graph, dependency_graph_amendment]   # earlier graphs are in Git history; this is the current plan
  nodes:
    det03_p0: {title: "DET-03 re-scope materialization", kind: documentation}
    det03_p1: {title: "Structural and ingest closure"}
    det03_p2: {title: "Observation and value-evidence slice"}
    det03_p3: {title: "Security detector slice"}
    det03_p4: {title: "DET-03 closure"}
    wp106:    {title: "Confirmed-relationship foundation (delivered; CCX-01 package 1)", id: WP-106, state: delivered}
  edges:
    - {id: C1, from: det03_p0, to: [det03_p1, det03_p2, det03_p3]}
    - {id: C2, from: [det03_p1, det03_p2, det03_p3], to: det03_p4}
    - {id: C3, from: det03_p2, to: [DET-04, OBS-02, CCX-01]}   # CCX-01 adds NOT_CHECKED to the existing observation record
    - {id: C4, from: det03_p1, to: ING-04}
    - {id: C5, from: [wp106, det03_p2], to: CCX-01}
    - {id: C6, from: CCX-01, to: [CCX-02, DET-05, DET-06]}
    - {id: C7, from: CCX-02, to: DET-05}
  no_edge:
    - "no DET-03 package depends on CCX-01, CCX-02, DET-05 or DET-06"
    - "no DET-03 detector reads confirmed relationships"
  notes:
    - "E4 (migration of line_total_mismatch and invalid_percentages, review of invalid_email_shape) moves to DET-05."
    - "E5 (standards policy and category harmonization) is unchanged and remains outside DET-03; STD-01, HARM-01 and RULE-03 are working titles."
    - "E6 (zero-row verification) and E7 (date-pattern vocabulary) become investigation steps inside packages 1 and 2; E8 (security review) is inside package 3."
    - "The two open CCX decisions gate CCX-01 only."
```
