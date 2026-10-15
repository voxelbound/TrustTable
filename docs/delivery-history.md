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

## Release plan chronology

This section holds the per-milestone status narrative that `docs/release-plan.md` carried before it was reduced to a milestone-level plan. The text is moved with its wording kept; where it says "Current status" it describes the state when it was written.

### v0.2 — status narrative

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

### v0.3 — status narrative

Current status: **complete.** Every feature above is implemented. `v0.3.0` is published and
was verified on a clean host with AI off (one pull, start and health check), and `REL-03` is
complete (D-049). The images are unsigned, unattested and not container-scanned, and the
local-AI setup was not exercised there. The project owner has recorded the `v0.2` and `v0.3`
milestones complete, each at the agreed scoped qualification level; `v0.2.0` and `v0.3.0` are
the published releases.

### v1.0 — status narrative

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
- **UI/UX redesign — slices S1 to S8a built (`UX-02` to `UX-09`); the Local AI architecture (S8b, `LAI-01`) is an unapproved design track.** An
  owner-confirmed PLAN CHANGE made the UI/UX redesign (`UX-01`, slices S1 to S8a) the next
  `v1.0` work, ahead of `DET-04` (D-066). Slice S1, the workspace and a deliberate start
  (`UX-02`, D-068), is built: choosing a file stages it for review and nothing is analyzed
  until Run. Slice S2, history, reopen and rerun (`UX-03`, D-069), is built: the Workspace
  lists recent analyses with open, run again and delete, and the Configure step notes when
  the exact file was analyzed before. Slice S3, the dashboard and progress (`UX-04`, D-070),
  is built: the Overview answers how much of the file the findings touch, how complete the
  data is, what has been reviewed, and where to look first, and progress is in business
  wording with AI work shown as separate and optional. Slice S4 (`UX-05`) is built in two
  parts: the findings review workspace (filtered previous, next and next-unreviewed
  navigation, a review-state filter, keyboard support and business labels, D-071), and
  persisted non-blocking AI enrichment (a saved, binding-checked AI explanation prepared
  on a bounded background worker, with the explanation route no longer calling a model,
  D-072), so `UX-05` is complete. Slice S5 (`UX-06`) is built in two parts: part a
  (D-073) measured the parse path and built the finding-scoped data inspector for a finding
  with affected rows; part b (D-074) reaches it from an observation's example rows and gives
  a column-wide finding a bounded window (example rows of observations about a column the
  finding is about, otherwise the start of the file, labelled as such), so `UX-06` is complete. Slice S6
  (`UX-07`, D-075) is built: the analysis areas are grouped under Review and Act and Export, the
  supporting areas say what they are for, and a Help area explains the terms. Slice S7 (`UX-08`,
  D-076 and D-077) is built: one explained AI-assistance setting and a browser-local Advanced
  mode. Slice S8a (`UX-09`, D-078) is built: a Local AI screen with a readiness checklist and a
  bounded connection test of the configured local runtime; it downloads, installs and manages
  nothing, and the product-managed mechanism stays `LAI-01`. It does not place `DET-04`, `CCX-01`,
  `CCX-02`, `DET-05`, `DET-06`, `OBS-02`, `ING-04`, `STD-01`, `HARM-01` or `RULE-03` in any
  milestone, and nothing is removed from `v1.0`. The sequencing of accessibility,
  browser-matrix and performance work relative to the redesign is not decided. The Local AI
  managed-provisioning architecture (S8b, `LAI-01`), a Rules and Expectations design track
  (`RULE-04`) and file-reading options (`ING-05`) are open, unapproved design tracks with no
  milestone placement. D-067 records the visible supersession of the machine-specific hardware
  wording in D-029 and the `AI-06` screening record. After manual end-to-end testing the
  human owner rejected the resulting UI/UX outcome as not meeting the intended
  business-application quality: the implementation is complete, the `UX-01` outcome is not
  accepted, substantial redesign is required before it can be, and no replacement design or
  redesign direction is approved yet.
- **Not yet done.** The rest of the list above is planned or has a `v0.1`-scoped baseline only.

## DET-03 closure record

This section holds the design record, per-package notes, boundaries and completion definition that the implementation backlog's `DET-03` item carried before it was compacted to a current item record. The text is moved with its wording kept; only cross-reference wording was adjusted where a sentence pointed at the backlog or at "this file". The current item is in [`implementation-backlog.md`](implementation-backlog.md).

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

## README detector catalogue bullet, as it read before it was condensed

The README's "Project status" bullet for `DET-03` enumerated the detectors and their behavior. The README now keeps only the closure facts and points to `docs/detector-framework.md` §16, which owns the catalogue; the bullet is kept here with its wording unchanged.

- **Detector catalogue (`DET-03`, closed as the Core detector catalogue, `docs/decision-log.md` D-065).** 26 detectors covering 28 of 41 catalogue entries; 13 carried by named successors. This closes the **Core** catalogue only: the 13 carried entries (value-distribution and time-based observations, checks that depend on your confirmed column meaning, geographic validation and the status/date conflict check) are **not built**, their successor items are planned with no milestone placement, and no detection is active for them, so the full catalogue is not built. An automated check compares the catalogue table in `docs/detector-framework.md` with the registered detectors and the successor items (it checks the table and the registry, not detector behavior). What the 26 detectors are: the twelve initial deterministic detectors and the prompt-injection risk detector, and then rows that are blank in every column; a column that writes yes/no values in more than one spelling (for example `Y`, `yes` and `TRUE`); dates before 1900, which are usually placeholders or typos; values in an email-named column that cannot be an email address (counts and row numbers only, never an address); a column of numbers written as text with a currency symbol, percent sign or thousands separator (such as `$1,234.50`), which stops it being summed or sorted as numbers; category values that differ only by punctuation or spacing (such as `New York` and `New-York`); column names that are the same once case, spacing and punctuation are ignored (such as `Order ID` and `order_id`); and three structural findings: a file that has a header but no data rows, columns whose header cell is blank, and a file in which an excessive share of rows had the wrong number of fields or of spreadsheet cells could not be read; and three observation-only detectors (a column that mixes value shapes such as numbers and words, a column whose dates are written in more than one format, and a column whose missing values sit mostly in one unbroken run of rows). Zero-padded codes and phone numbers are never reported as numbers stored as text. Only the old-dates finding offers a proposed validation rule among these newer detectors, none of the three structural findings offers one, and the column-name finding reads names only, never a value. The two structural findings about unreadable rows and cells read only counts and example positions that the file reader had already noticed, never a cell value or a reader message, and values cut short by TrustTable's own size limits are never counted as a defect in your data. The **possible prompt injection** finding labels what it matched as a prompt-injection instruction, an exfiltration instruction or a secret request, is one finding per column worded as a "possible risk, not confirmed malicious intent", and stores only a short excerpt; a column it flagged before can now rise in severity, and the trust score can fall, when it also contains one of the newly recognised phrases; it does not detect text hidden with look-alike letters from other scripts, leetspeak, encodings such as base64, or a request split across cells. Findings appear with built-in guidance; a separate, read-only list of **data observations** on the Overview states counts and example row numbers only (never a cell value), has no severity, confidence or priority, never changes the trust assessment, is not sent to an AI model and is not part of a report or export; it offers no built-in guidance or proposed rule and cannot yet be dismissed. You can record, change and withdraw a start-date and end-date relationship between two columns of a completed analysis, as immutable versions with a full history (`docs/decision-log.md` D-060), but **nothing reads it yet**: no check is based on it, and every response states `check_status: "not_active"`, which means no check exists, not that the data passed one.

## Backlog item status records

This section holds the delivery detail that the implementation backlog's completed items carried in their `Status` text before the backlog was compacted to current item records. The text is moved with its wording kept. The current status of each item is in [`implementation-backlog.md`](implementation-backlog.md).

### AI-07 — annotation

> Annotation (2026-09-17, `D-036` sequencing): inserted here, between
> `API-02` and `AI-05`, per `D-033`'s appended sequencing amendment.

### REL-02 — status and delivery steps

Status: complete. `REL-02` is complete (`docs/decision-log.md` D-041 to D-045). It was delivered in
three ordered steps:

1. *Repository-side path* (D-041): `docker-compose.release.yml` (pull-only, requires
   `TRUSTTABLE_VERSION`) and a tag-gated publish workflow (`docs/release-images.md`), tested
   structurally and against locally built images. Publishing, tagging and package
   visibility stay with the repository owner.
2. *Local-AI qualification* (the fourth bullet above). The instrument exists: a harness that
   runs the product's own finding-analysis path over one finding per detector, with and
   without finalized confirmed context, and records fill rate, fallback rate and
   harness-measured latency (`docs/local-ai-qualification.md`, D-043); it was proven only
   against the real explanation route with stubbed providers. The bullet is **waived** by
   the human owner for `v0.2` (D-044): no real-model benchmark of this path was completed
   and none is planned as a replacement. The waiver is **not a pass**, and no minimum,
   recommended, baseline-tier or general hardware claim may be inferred from it. The
   bullet's "on baseline hardware" wording is preserved as written and is unvalidated by
   this project's own evidence.
3. *Protected publish and clean-host verification* (the first three bullets; D-045): the
   `v0.2.0` images were published to GHCR, and the pull-only path needs no build step and no
   PyPI, npm or base-image access. The release was installed on a clean Linux host with only
   GitHub and GHCR access and no GHCR credentials, **narrowed by the human owner to one
   AI-off pull, start and health check**: the offline-provisioned model and the model
   connectivity check were not exercised there. The guide states the verified commands and
   marks what the run did not cover.

Also recorded (D-042): before the qualification, the backend test suite was made hermetic
against a developer's local provider configuration and the trust-boundary meaning of the
`confirmed_context` envelope slot was recorded. Neither satisfies any of the four bullets.

### EXP-01 — status and slices

Status: complete. The backend scope is complete; the report screen (`UI-03`) and report deletion with
the analysis (`DEL-01`) are separate items. Delivered in four slices:

1. The JSON and YAML rules exports (`GET /analyses/{id}/exports/rules.json` and
   `rules.yaml`, `docs/api-specification.md` §12). Only validated rules are exported.
2. The deterministic Markdown report renderer and immutable report snapshot, as a library
   (`trusttable_backend.exports.report_markdown`), including the AI-processing security
   section, which reports only recorded state (`D-046`).
3. Report snapshot persistence (a new additive `reports` table) and the four report routes
   (`docs/api-specification.md` §12), with the OpenAPI contract and generated client
   regenerated. Reports are rendered once and stored; downloads never re-render.
4. The durable per-analysis record of AI enrichment calls (`D-047`), so new reports state
   counts, what may have been sent, the model location and the protections.

### DEL-01 — status

Status: complete. `DELETE /analyses/{id}` is implemented (`docs/api-specification.md` §6, `D-048`): the
analysis and all of its reports are removed in one transaction, a running analysis is
cancelled and cannot be brought back by its worker, and the stored bytes are overwritten in
the database file. The deletion control and its completion message are part of `UI-03`. No
`analysis_deleted` event is emitted because no lifecycle event log exists yet.

### UI-03 — status and slices

Status: complete for its named screens, delivered in five slices; backend-dependent gaps
remain outside this item.

1. The analysis lifecycle controls in the analysis layout: cancel, retry (opens the new
   attempt) and delete with an accessible permanent-removal confirmation
   (`docs/ui-specification.md` §3).
2. The report screen (`docs/ui-specification.md` §4.10): choose the report options, generate
   an immutable snapshot, list stored reports and download a report's Markdown.
3. The rules screen (§4.9): list rules with their latest results, expand read-only details,
   re-run and delete a rule, and download the validated rules as JSON or YAML.
4. The finding review controls on the finding detail screen (§4.7) over the existing review
   route; the findings list shows each review state.
5. The technical details screen (§4.11), from existing routes only.

Gaps outside this item: editing rule parameters and the enabled toggle (no update route),
filtering findings by review state (no filter), and exposing detector thresholds and
analysis-level prompt/model metadata.

### REL-03 — status

Status: complete. `REL-03` is complete; the `v0.3` milestone decision is the owner's.

- Repository side: the backend version is `0.3.0`, and one acceptance test
  (`backend/tests/api/test_v03_complete_workflow.py`) drives a CSV through the whole
  persisted workflow: analysis, findings, a finding review, a rule created and run, the
  rules export, a stored Markdown report, a restart and permanent deletion.
- Release: the owner pushed the tag `v0.3.0` (peels to
  `5053249adacca3c46276daa91f8ea1ff0ccc945d`), the release workflow passed, and a clean
  Linux host with no GHCR credentials pulled and started the release with AI off
  (`docs/decision-log.md` D-049). As for `REL-02`, the clean-host check is one AI-off pull,
  start and health check; the local-AI setup was not exercised. The images remain unsigned,
  unattested and not container-scanned.

### ING-03 — status and slices

Status: complete; the item is complete (`ING-03`). It was delivered in four slices:

1. The secure XLSX parser (`parsers/xlsx_parser.py`, `parse_xlsx`): worksheet selection by
   name or the first visible sheet, stored values read as literal text with formulas never
   evaluated, rejection of macro-enabled, encrypted, malformed and path-traversal
   workbooks, and expansion, entity and resource limits (`docs/decision-log.md` D-050).
2. The API accepts `.xlsx` (`POST /analyses` with the optional `worksheet` field):
   worksheet selection or `WORKSHEET_REQUIRED`, upload-time refusal of macro-enabled,
   malformed and over-limit workbooks, a format-aware pipeline that reads the chosen
   worksheet at every stage, `selected_worksheet` in the dataset summary, and retry that
   keeps the format (D-051).
3. The Start screen accepts `.xlsx`, asks which worksheet to analyze when the API answers
   `WORKSHEET_REQUIRED`, uploads the same file with the picked worksheet and shows the API's
   refusal messages; the Overview and Technical details screens name the worksheet analyzed
   (D-052).
4. The configured limits (documented in `docs/configuration.md`): `MAX_FILE_SIZE_MB`, `MAX_ROWS`, `MAX_COLUMNS`, `MAX_WORKSHEETS`,
   `MAX_UNCOMPRESSED_WORKBOOK_MB` and `MAX_CELL_COUNT` (with the column-name and text-value
   length settings) are read from the settings on every CSV and Excel parse, in the upload
   inspection and each pipeline stage, through one factory (`analysis/parse_limits.py`);
   with no variables set behavior is unchanged (D-053).

Checked and outside the item: `POST /datasets/inspect` (marked optional in the API
specification and assigned to no backlog item), date interpretation (no authoritative
document asks for it; formatting is ignored by design, so a date stored as a serial number
is shown as that number), and the Playwright worksheet-selection scenario (a `REL-04`
test-gate item under `docs/testing-strategy.md` §2.4).

### UX-01 — implementation defects and drift list as written when the redesign was specified

This list was written when the redesign was specified: an entry marked **Resolved** was resolved by the slice
it names, and an entry without that mark was not re-verified when the slices were
completed, so it may be out of date and is not a statement of current behavior:

- `PROMPT_INJECTION_DETECTION_ENABLED` is documented as the gate of the prompt-injection
  detector and is consumed by nothing; a setting must not be presented that does not
  control the behavior it claims to control.
- The frontend proxy sets no read timeout or request-body size, so upload limits and
  long AI requests may be inconsistent with the backend limits and with
  `LLM_TIMEOUT_SECONDS`; to be verified, with server-side enforcement as the authority.
  **Resolved for uploads by `UX-02` (D-068):** the proxy now applies no size limit and
  streams bodies with 300-second read and send timeouts, and the backend is the size
  authority. Whether a long AI request fits the proxy timeouts is not re-verified here.
- The Start screen states that AI is disabled regardless of configuration, and a
  documented `GET /ai/status` route does not exist. **Resolved by `UX-02` (D-068):**
  `GET /ai/status` exists and the Workspace and Configure step show its status.
- Raw internal values (categories, severities) appear in the interface.
- Placeholder text on the Overview ("coming soon") describes capabilities that exist.
- `ANALYSIS_RETENTION_HOURS` is declared and consumed by nothing.
- `docs/api-specification.md` says the source file is stored; the code stores the
  content in the database with a nominal storage location.
- The explanation route calls the model on every request and stores nothing, and the
  finding screen waits for it.

### UX-02 to UX-09 — status records

**UX-02 (S1).** Status: built (`docs/decision-log.md` D-068; migration `0009`; settings
`STAGING_MAX_COUNT`, `STAGING_MAX_TOTAL_MB` and `STAGING_TTL_MINUTES`). Delivered as
specified below with the engineering choices recorded in D-068; no durable Dataset, no
history, hash lookup or "analysed before" notice (`UX-03`), and no Analyses, Settings or
Help navigation until those slices ship. `UX-03` onward remain planned and unauthorized.

**UX-03 (S2).** Status: built (`D-069`). The Workspace lists the 20 newest analyses with open, run
again and delete; `GET /analyses` and `POST /analyses/{id}/rerun` are built; the
Configure step shows an "analysed before" notice from an indexed lookup over live,
completed analyses, which forgets an analysis when it is deleted. The name hint is
filename-only and describes no difference. Not built: paging, search, an *Analyses*
navigation entry.

**UX-04 (S3).** Status: built (`D-070`). The Overview shows the trust assessment, an *At a glance*
group (distinct rows affected, cells filled in with their sampled-or-full scope, review
progress), the distribution of findings by severity and by kind of problem, the
columns with the most findings, the top findings, observations as *Worth knowing* and
the dataset summary; progress uses business wording and states that AI work is
separate and optional. `GET /analyses/{id}/summary` is built and carries counts only.
Not built: trends, comparison with an earlier analysis, a data-quality percentage
beside the trust assessment, a numeric progress or time estimate. `UX-05` onward remain
planned and unauthorized.

**UX-05 (S4).** Status: **built** (`D-071`, `D-072`). Part a (frontend only): previous, next and
next-unreviewed navigation over the filtered, priority-ordered list with the filters
carried in the address, a review-state filter, keyboard shortcuts that are inert while
typing, and business labels for category and severity. Part b: persisted, non-blocking
AI enrichment per finding. The explanation route no longer calls a model; a short
`POST`/`GET .../ai-enrichment` pair starts and reports it; the call runs on a bounded
in-process worker; a saved result is bound to the finding, confirmed-context version,
model identity and prompt or contract version and is stale when any changes; a restart
fails anything left preparing; saved output is deleted with its analysis; the screen
shows the built-in guidance at once with a separate AI state. Not built, and not part
of this item: AI for all findings at once (the batch seam is an interface only), and
`rule-proposal`, which still calls the model within its request.

**UX-06 (S5).** Status: **completed** (`D-073`, `D-074`). Part b (`UX-06b`) is built: the inspector is
reached from an observation's example rows (`observations/{id}/row-context`) and a
finding that names no rows opens a bounded window the server chooses
(`findings/{id}/column-context`): the example rows of observations about a column the
finding is about (at most 20), otherwise the start of the file, labelled as such and
never marked as evidence of the finding. Every read shares the part a bounds and no-store header. Part a, built
earlier, is: the measurement
(`backend/scripts/measure_inspector_parse.py`, figures recorded in D-073) and a
finding-scoped grid inspector for a finding that has affected rows, reached from the
finding screen: scrolling both ways, sticky headings and row numbers, affected rows and
columns marked, previous and next affected row with an honest position, a return to the
finding, inert text with long values shortened until revealed. The row limit stays 25 a
side; two reads at most run at once (`429 INSPECTOR_BUSY`), a window is bounded in
characters (`size_limited`), the response is `no-store`, and no parsed-rows cache was
added. Not built, and not part of this item: a general dataset browser, search, sampling,
a durable Dataset, and any row data in AI input, canonical evidence, reports or exports.

**UX-07 (S6).** Status: **completed** (`D-075`). The analysis screens are grouped as *Review* (Overview,
Findings, Observations, About this data) and *Act and Export* (Reports, Rules, Technical
details); Observations has its own screen; each supporting area states its purpose,
availability, why it matters and the next step; Rules say they apply to this analysis
only and offer no creation or editing; a **Help** screen explains findings and
observations, the trust assessment, provenance, sampled and full, AI and Rules; loading
and empty states share one pattern. Technical details stay visible to everyone because
Advanced mode belongs to `UX-08` (`UX-08b`, D-077, now shows them only in Advanced mode).
No backend, API or dependency change.

**UX-08 (S7).** Status: **completed** (`D-076`, `D-077`). Part b (`UX-08b`) is built: a **Settings** screen
(`/settings`, in the workspace navigation) that explains AI assistance and changes or resets it through
the versioned API, shows only what the server confirmed, states a setting managed by the
installation as read-only with its reason, and states a refused change in plain words; and
a browser-local **Advanced mode** that shows the runtime and model configuration (requested
only while Advanced mode is on) and the Technical details area (listed only in Advanced
mode; the address stays reachable and says so). Advanced mode is a display choice, not a
security control. No backend, API or dependency change. No AI profile and no retention
setting. Part a (`UX-08a`) is built: an additive `app_settings`
table (migration 0012), one allowlisted boolean setting (`ai_assistance`), the effective
value computed on the server as explicit deployment override, then stored value, then
off (an override is `LLM_PROVIDER` set in the environment or `.env`, never inferred), the
`/settings` API with versioned writes and reset, AI status, enrichment, explanation and
rule proposal following the effective value, an Advanced-only response for the runtime
and model configuration, `LLM_PROVIDER` commented out in `.env.example` with tests that
packaging sets no managed key, and the two settings that nothing consumes documented
honestly. `UX-08` is completed by part b. Remaining after it: `UX-09`, still planned and
unauthorized.

**UX-09 (S8a).** Status: **completed** (`D-078`). Built: `GET /ai/readiness`, five ordered steps (assistance
on, a runtime named, on this machine, answering a short check, a model named) computed
from the effective setting and one capped liveness probe made by that request (the same probe helper as `GET /ai/status`, not a shared result);
`POST /ai/connection-test`, with no body and no client-supplied target, that checks only a
configured runtime on this machine, makes no completion call, allows one test in flight and
a minimum gap between tests, and returns a closed set of outcomes with fixed wording and no
address, path or exception text; and a **Local AI** screen (`/local-ai`, linked from
Settings, the Local AI status panel and Help) with the checklist, *Test connection* and
plain guidance that setup happens outside TrustTable. A reachable answer says only that the
runtime answered, not that the model works. No compatibility claim about a model or
hardware, no download, installation, start, stop or model management, no profile, no new
setting, no schema or dependency change. `LAI-01` remains an unapproved design track.
