# TrustTable

TrustTable is a local-first, AI-assisted data quality investigator for business datasets.

It combines deterministic profiling and rule-based detection with evidence-grounded LLM interpretation. Calculated facts remain authoritative; AI is used to infer context, ask focused questions, explain findings, recommend remediation, and describe validation rules.

## Quick start (Linux)

Requires Docker Engine 20.10+ with the Compose v2 plugin.

```sh
git clone https://github.com/voxelbound/trusttable.git
cd trusttable
docker compose up --build
```

Then open <http://127.0.0.1:8080>, choose **Try the sales demo** (or upload a `.csv`), and open any finding. This is the whole product **without AI**: TrustTable's deterministic findings and evidence, plus built-in guidance for each finding — an explanation, possible business impact, a remediation suggestion and a proposed validation rule.

Optionally add a **local AI model** (`llama.cpp`, no account or API key, no Hugging Face access at runtime) for an AI-assisted version of that analysis. Every AI answer is validated, advisory, and never overrides the deterministic results. The complete Linux guide — running without AI, provisioning the GGUF model, starting `llama-server`, the environment settings, Docker versus native, verification for backend, frontend and model, and troubleshooting — is **[Install and run TrustTable on Linux](docs/installation-linux.md)**.

> A GitHub-and-GHCR-only install (no PyPI, npm or container base-image access) is **not supported yet**: `docker compose up --build` builds the images from source. Publishing images is a planned `v0.2` packaging requirement; the guide states the current limitation exactly.

## Project status

**v0.1 — Deterministic vertical slice: complete and recorded release-ready.** Every bullet in `docs/release-plan.md`'s v0.1 checklist is implemented and tested; all three release-qualification areas (performance evidence, security qualification, release-candidate testing) have real, scoped-baseline evidence; the human owner recorded v0.1 milestone-complete/release-ready. This does **not** itself constitute full `docs/testing-strategy.md` §8 release-candidate CI-gate compliance: the full multi-browser/viewport matrix, SBOM/container scan/license check, full deterministic/AI evaluation, and migration tests remain open, mostly scoped to the later v1.0 milestone.

**v0.1.1 — Investigation UX: complete.** `FIND-01` (row context for row-anchored findings) — this milestone's sole planned deliverable — is implemented in full: the row-context API endpoint, and a Finding Detail UI section with expand and Prev/Next navigation across a finding's own affected rows (see "Delivered work" below).

**Current milestone: v0.2 — Local AI beta.** The model/runtime decision gate is closed (Qwen3.5-4B-Q4_K_M on `llama.cpp`, baseline/CPU-oriented profile — `docs/decision-log.md` D-034/D-035); `Settings.llm_provider` still defaults to `"disabled"`, so every capability below degrades gracefully. Everything through `UI-02` is now complete: the AI provider interface and its three providers (disabled/mock/real `llama.cpp`), the local-AI benchmark harness and its hands-on evaluation, deterministic and AI-assisted context inference (`CTX-01`–`CTX-03`), the Context confirmation service (`API-02`), `llama-server` runtime hardening (`AI-07`), a two-phase context/AI architecture decision (`docs/decision-log.md` D-037 — the deterministic pipeline stays unchanged and unattended; context confirmation and AI interpretation are a second, optional, additive enrichment phase over an already-completed analysis), and `UI-02` (Context and AI UI) itself, delivered across two slices: grounded finding explanations (a real route plus a Finding Detail display) and the real Context screen (editable fields with provenance, guided questions, confirm/finalize — see "Delivered work" below for exact detail). The prompt-injection adversarial evaluation (`EVAL-AI-01`) is also complete: a compromised-model evaluation against the real routes proved that an adversarial response cannot become an accepted AI interpretation that calls the dataset perfect or tells the user to disregard findings, and closed a real validator gap it found (`docs/decision-log.md` D-039). The AI-assisted finding analysis is also complete (`AI-08`, `docs/decision-log.md` D-040): four grounded, advisory sections per finding from one structured, validated model response — or from built-in guidance when AI is off or its answer is rejected. **Remaining for `v0.2`: `REL-02` (the `v0.2` packaging item) only**, which now also carries the Linux-deployment acceptance requirements (published images and a verified pull-only install on a fresh Linux host).

The product, domain model, API boundaries, detector framework, frontend architecture, testing strategy, threat model, release plan, and implementation backlog were all defined before production implementation began (see `docs/`).

### Delivered work

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
- **DET-SEC-01** — the prompt-injection risk detector (`security.possible_llm_prompt_injection`), completing the detector catalogue at 13/13.
- **RISK-01** — deterministic risk scoring: per-finding priority scores and a four-label dataset trust assessment, computed with no AI/LLM input path at all.
- **API-01** — the analysis API: an in-memory orchestration engine (parsing → profiling → detection → scoring) exposed over real `/api/v1` HTTP routes — `POST /demo/sales`, `GET /analyses/{id}`, `.../status`, `.../profile`, `.../findings`, `.../findings/{finding_id}`, `.../findings/{finding_id}/evidence`, `POST .../cancel`.
- **UI-01** — the basic investigation UI, complete: a Start screen (sales-demo action plus generic CSV upload), a named-stage progress view, an Overview screen (trust assessment, top findings, dataset summary), a Findings list (severity/category/search filtering), a Finding detail screen (evidence, representative examples, technical metadata, and — at the time this package merged — honestly-disclosed not-yet-available business-impact/remediation/validation-rule/review sections; the first three are now real, see `AI-08` below), and a dedicated prompt-injection-warning presentation for `ai_processing_security` findings.
- **REL-01** (scoped) — Docker Compose production-configuration hardening: both services now restart automatically after an unexpected exit; SBOM generation and container image scanning are explicitly deferred to `SEC-01`'s later, full scope.
- **API-01, extending** — generic CSV file-upload analysis creation (`POST /api/v1/analyses`, CSV only, with extension/size validation and filename sanitization; `.xlsx` remains `ING-03`, a later backlog item) — completing every remaining `docs/release-plan.md` v0.1 checklist item.

**v0.1 release-qualification (scoped baselines)**

- **PERF-01** (v0.1-scoped) — a performance baseline across 10k/100k/250k-row and one wide-column synthetic case; full v1.0-scale benchmarking and tuning remain open.
- **SEC-01** (v0.1-scoped) — a security-qualification review closing a logging-safety test gap and adding an unsafe-HTML-rendering regression guard; SBOM generation, container scanning, and license checking remain `SEC-01`'s later, full scope.
- **BROWSER-01 / A11Y-01** (v0.1-scoped) — release-candidate testing qualification: the first live execution of the Chromium/axe-core browser-accessibility suite against the real Docker Compose stack (6/6 tests passing); the full multi-browser/viewport matrix and full accessibility suite remain open, later v1.0-milestone scope.

**v0.1.1 — Investigation UX (complete)**

- **FIND-01** — row context for row-anchored findings: `GET /api/v1/analyses/{id}/findings/{finding_id}/row-context` returns a bounded (max 25 rows per side) physical-neighborhood window around one of a finding's own affected rows, reconstructed on demand from the analysis's retained upload bytes (never a standing `ParsedDataset`); the Finding Detail screen's new "Row context" section renders it with the anchor row highlighted, an expand control, and, for findings with more than one affected row, Prev/Next navigation between them. Not `Evidence`, not in Report/export output, never automatic AI-prompt input (`docs/decision-log.md` D-025).

**Local AI beta (v0.2 — begun)**

- **AI-01** — the AI provider interface: a framework-independent contract package (the six model-call operations, request/response/health-check shapes, a provider-error hierarchy, and the `AIProvider` protocol every provider implements against).
- **AI-02** — the two non-real providers required by `docs/product-requirements.md` §12: `DisabledProvider` (`llm_provider=disabled`, `D-006`'s "complete AI-disabled mode") and `MockProvider` (`llm_provider=mock`, configurable static or dynamic output, proven capable of producing and having rejected genuinely adversarial "attempt to follow the injected instruction" output against the real `validate_model_output`), plus a small `create_provider` factory.
- **AI-03** — the real local-inference provider: `LlamaCppProvider` (`llm_provider=llama_cpp`), a real `httpx`-based client for `llama.cpp`'s `llama-server`, reusing `build_safe_prompt` unmodified and never calling `validate_model_output` itself. Registered in the provider factory; `Settings.llm_provider`'s default remains `disabled`. No live-model test runs in CI (deterministic `httpx.MockTransport` tests only, matching the benchmark-only adapter's own precedent). **Updated (`WP-065`, defect fix):** at the time this package merged, no FastAPI route called it yet — that has since changed; see the `UI-02` slices below.
- **AI-06** (harness plus completed hands-on evaluation) — a persistent, config-driven local-AI benchmark harness: six fixed, versioned task fixtures (one per `AIOperation`) grounded in real demo-dataset evidence, and a runner scoring structured-output validity/groundedness, latency, bounded retry rate, and repeated-call consistency for any `AIProvider`. The full hands-on evaluation (six-candidate first-round screening, a blind qualitative comparison, and a controlled performance/resource comparison between the two finalists) is complete and published (`docs/evaluation/ai-06-first-round-model-screening-2026-09-16.md`); the resulting model and runtime decision is recorded in `docs/decision-log.md` D-034/D-035.
- **AI-04** — local runtime documentation: a hands-on setup guide (`docs/local-development.md`) for installing `llama.cpp`'s `llama-server`, manually obtaining and verifying the baseline model (Qwen3.5-4B-Q4_K_M), starting it on the baseline/CPU-oriented profile, and configuring TrustTable's `LLM_PROVIDER`/`LLM_BASE_URL`/`LLM_MODEL` settings to reach it — no paid account required.
- **CTX-01** — deterministic context hypotheses: a framework-independent, AI-free heuristics module (`context_inference/heuristics.py`) that infers candidate keys, business dates, measure/dimension roles, row grain, primary entity, and a narrow disclosed probable-domain guess directly from `PROF-02`/`PROF-03`'s already-computed column facts — no AI/LLM call of any kind. `currency_behavior` and `expected_business_rules` are honestly left unresolved (no deterministic signal exists for either yet).
- **CTX-02** (enabling slice) — validated AI context inference: `context_inference/ai_context.py` calls a real `AIProvider` for `AIOperation.CONTEXT_INFERENCE`, grounded in `CTX-01`'s deterministic context (serialized into the trust boundary's untrusted `confirmed_context`, per the existing architecture) plus optional bounded dataset samples (off by default), validates every response through `SEC-02`'s real `validate_model_output`, retries once with feedback on rejection, and never raises on provider failure. An accepted response becomes one new `probable_domain` hypothesis that wins consolidation over `CTX-01`'s own narrower heuristic. At the time this package merged: not yet wired into `analysis.service`, any `AnalysisState`, or any API route — no product-visible behavior change for any existing analysis; `Analysis.security_exposure` unchanged. **Superseded (`UI-02` slice 2, `WP-064` r2):** `GET .../context` now calls this module's `run_context_inference` on an analysis's first inference (see the `UI-02` slice 2 bullet below) — `Analysis.security_exposure` remains unchanged regardless, and must never be read as reflecting this separate call (`docs/decision-log.md` D-038).
- **CTX-03** (generation only) — guided questions: `context_inference/guided_questions.py` deterministically generates up to five business-language `ClarificationQuestion`s (`docs/domain-model.md` §10), one per `CTX-01`/`CTX-02` context field still unresolved (`probable_domain`, `row_grain`, `primary_entity`, `currency_behavior`, `expected_business_rules`) — never more, by construction, matching the product's own "no more than five" rule exactly. Deliberately deterministic rather than AI-generated, since no structured multi-question output shape exists in this codebase's AI trust boundary yet.
- **API-02** (service-layer enabling slice, no HTTP route yet) — context confirmation: `analysis/service.py` gains `get_or_infer_context`/`get_guided_questions`/`confirm_context_fields`/`answer_guided_question`/`finalize_context`, plus `ClarificationAnswer` (`docs/domain-model.md` §11, implemented for the first time). This is a strictly additive layer over an already-`COMPLETED` analysis, with optimistic-concurrency versioning (`docs/api-specification.md` §9's "requires resource version"). **`AnalysisState` and `run_analysis` are deliberately unchanged** — wiring the pipeline itself to pause for confirmation would regress the already-shipped `v0.1`/`v0.1.1` UI's poll-until-`COMPLETED` behavior, so that remains an open, later, human-directed product decision. `CTX-02`'s AI augmentation is correspondingly not invoked either. The actual FastAPI HTTP routes for this already-specified contract, live-pipeline wiring for `CTX-01`/`CTX-02`/`CTX-03`, and `UI-02` remain open.
- **AI-07** — `llama-server` runtime hardening: `llama.cpp`'s `llama-server` is treated strictly as inference infrastructure, never a user-facing application — TrustTable is the sole user-facing surface. The documented/supported runtime profile now starts `llama-server` with `--no-webui` on its own dedicated port (`8081`), distinct from TrustTable's own frontend port (`8080`), eliminating a real host-port collision (`docs/decision-log.md` D-036). `LLM_BASE_URL`'s default value and documented example updated to match. Does not reopen `D-034`/`D-035` — the Qwen3.5-4B-Q4_K_M + `llama.cpp` CPU-oriented baseline is unchanged.
- **AI-05** (enabling slice) — grounded finding explanations: a new `domain/explanation.py` `FindingExplanation` value object, `explanation/deterministic.py` (no AI, always available — the first implementation of `docs/product-requirements.md` §5.7's "deterministic explanations" AI-disabled-mode requirement) and `explanation/ai_explanation.py` (calls a real `AIProvider` for `AIOperation.FINDING_EXPLANATION`, grounded in one finding's own captured `Evidence`, validated through `SEC-02`'s existing `validate_model_output` — whose generic schema already structurally enforces every one of `AI-05`'s own backlog rejection rules: unknown evidence, unknown columns, incorrect numbers, and no way to remove a finding or replace its score). At the time this package merged: not yet wired into `analysis.service`, any API route, or the UI. **Superseded (`UI-02` slice 1, see below):** `GET .../findings/{finding_id}/explanation` now calls this module through the API route layer, never `analysis.service` — that module's own no-`ai_boundary`/`ai_provider`-import guarantee and `Analysis.security_exposure` remain unchanged and independent of this call (`docs/decision-log.md` D-038).
- **`UI-02` slice 1** — the first real, user-visible piece of `v0.2`'s AI capability: `GET /api/v1/analyses/{id}/findings/{finding_id}/explanation` always returns `AI-05`'s deterministic explanation, additionally attempting the validated AI path through the real provider factory when `LLM_PROVIDER` is not `disabled` (the default), falling back to the deterministic explanation on rejection or provider error. `FindingExplanation` gains `provider_name`/`model_identifier` (additive, `docs/decision-log.md` D-037's disclosed reconciliation step toward `docs/domain-model.md` §14's `AIInterpretation` shape). The Finding Detail screen's new "Explanation" section displays the narrative, provenance, and model location.
- **`UI-02` slice 2 (completes `UI-02`)** — five new real routes (`GET`/`PUT /analyses/{id}/context`, `GET /analyses/{id}/questions`, `POST .../questions/{question_id}/answer`, `POST /analyses/{id}/finalize`) wiring `API-02`'s already-built, already-tested service methods to HTTP for the first time, plus the real Context screen (`docs/ui-specification.md` §4.4, reachable from Overview): the five editable single-value context fields with a provenance label per field, the four column-role fields shown read-only, the guided-questions list (suggested-answer buttons and free text), and a Finalize action. **Pre-merge correction (`docs/decision-log.md` D-037's appended closure note):** the first version of this package left `CTX-02` and the explanation path structurally disconnected from context confirmation. Corrected before merge — `GET .../context` now calls `CTX-02`'s real validated AI context inference on an analysis's first inference only (never re-invoked once cached), and `GET .../findings/{finding_id}/explanation`'s envelope now carries the finalized `DatasetContext` once `POST .../finalize` has actually been called, making `finalize` the real, observable trigger for context-grounded enrichment. `finalize_context`'s own service-layer behavior (marks context finalized, no synchronous fan-out AI call across every finding) is otherwise unchanged.
- **Defect fix — AI exposure/provenance disclosure semantics (`docs/decision-log.md` D-038, `WP-065`):** the human owner found, via manual end-to-end testing against a real `llama.cpp` runtime, that the Finding Detail screen could show an accepted AI explanation (`"AI interpretation — llama_cpp (...)"`) while simultaneously claiming, via a misleading generic "AI model enabled" row and `PromptInjectionWarning`'s unrelated `security_exposure`-derived fields, that no AI call was made. Both underlying signals were individually correct but had different, un-disclosed scopes (`Analysis.security_exposure` describes only the deterministic pipeline's own, permanently-`False` raw-sample-exposure posture; the explanation route's own AI usage is a separate, independently-configured call). Fixed by a new `FindingExplanationResponse.ai_call_status` field (`not_configured`/`attempted_accepted`/`attempted_rejected`/`attempted_provider_error`), removal of the misleading Technical-metadata row, reworded `PromptInjectionWarning` copy, and corrections to stale documentation (`docs/architecture.md`, `docs/api-specification.md`) that had claimed no route called a provider after `UI-02` had already shipped ones that do. Does not reopen `D-034`/`D-035` — the manual test used `Qwen3.5-9B` locally, not adopted as any baseline change.
- **EVAL-AI-01** — prompt-injection adversarial evaluation: an end-to-end suite (`backend/tests/security/test_prompt_injection_adversarial_evaluation.py`) drives the real routes and provider factory with a compromised model that obeys the injected instruction ("claim this dataset is perfect"), including variants that cite genuine evidence IDs. It found that `SEC-02`'s output validator was purely structural — a schema-valid narrative-only "this dataset is perfect" response would have been accepted and shown as an AI interpretation — so a bounded, closed claim screen was added to it (`docs/decision-log.md` D-039): unsupported whole-dataset claims and instructions to disregard deterministic results are now rejected, and the user sees the deterministic explanation. The evaluation proves findings, evidence, severity and the trust assessment are byte-for-byte unchanged, retry feedback and logs carry reason codes only, honest narratives are still accepted, and the adversarial context-inference path leaves context unchanged. The screen is lexical and evadable by a creative paraphrase — a documented limit, with deterministic authority remaining the guarantee. The Finding Detail protections list states the new protection. Asserting the applied protections in the *exported* report is carried to `v0.3`, when that report exists.
- **AI-08** — grounded AI analysis, recommendations and a deployable local-AI experience. Each finding now has one coherent analysis: an explanation, possible business impact, a remediation suggestion and a proposed validation rule. With a local model these come from one *structured*, constrained response (`finding_analysis_v1`) that is validated role by role — impact statements are presented only as potential impacts with the condition they depend on, labelled conditional or informed by your confirmed context by TrustTable itself (a model cannot award its own text the standing of an established fact); remediation is advisory only and never changes your data; the proposed rule is a proposal, never active. Without AI, or when a model's answer is rejected or fails, the same four sections come from built-in guidance for all 13 detectors, and the deterministic findings, evidence, severity and trust assessment are unchanged either way. Only context you confirmed and finalized is ever sent to a model. The UI shows a readable identity ("Local AI · llama.cpp · Qwen3.5 4B") and never a file path. Linux install and local-AI setup are documented in [`docs/installation-linux.md`](docs/installation-linux.md), and the Docker Compose backend can now reach a host `llama-server` on Linux. The rule engine, rule execution, persistent review and exports remain `v0.3` (`docs/decision-log.md` D-040).

The first production target is a local, single-instance application that:

- runs through Docker
- analyzes CSV and Excel files
- remains useful without an LLM
- optionally uses a locally downloaded model through `llama.cpp`
- requires no paid inference API
- treats uploaded values as untrusted data
- detects and reports possible prompt-injection content
- is tested against explicit release gates

A public hosted demonstration is deliberately deferred until the local application is complete and proven.

## Running it today

The backend and frontend skeleton can be started right now, native or
through Docker Compose — see [Local development](docs/local-development.md)
for exact commands. The bundled deterministic demo dataset is
[`demo-data/sales_demo.csv`](demo-data/sales_demo.csv).

The full deterministic pipeline (CSV parsing, type inference, profiling,
detection, and risk scoring) is reachable both through the running
backend API directly (`POST /api/v1/demo/sales`, `POST
/api/v1/analyses` (CSV upload), `GET /api/v1/analyses/{id}`,
`.../status`, `.../profile`, `.../findings`, `GET
.../findings/{finding_id}`, `GET .../findings/{finding_id}/evidence`,
`GET .../findings/{finding_id}/row-context`,
`POST .../cancel`) and through the real frontend: open the running app
and either choose "Try the sales demo" or upload your own `.csv` file
on the Start screen to see a progress view, a trust-assessment Overview,
a filterable Findings list, and — by selecting any finding — a Finding
detail screen with its evidence, an explanation, possible business impact,
remediation and a proposed validation rule (built-in guidance, or an
AI-assisted version when a local model is configured), a "Row context"
section around any of its own affected rows (row-anchored findings only), or, for the
prompt-injection detector's own finding, a dedicated warning
presentation explaining what was detected, whether it was sent to a
model, and what protections apply.
Excel (`.xlsx`) upload is not yet supported (**ING-03**, a later
backlog item) — only `.csv` files are accepted today.
[Local development](docs/local-development.md#exercising-the-deterministic-profiling-pipeline-directly)
still has a reproducible way to exercise the pipeline directly in
Python, without the API, if preferred.

## Planned user workflow

```text
Upload → Understand → Analyze → Review → Export
```

1. Upload a CSV or Excel dataset, or load the synthetic sales demonstration.
2. Review TrustTable's inferred understanding of the dataset.
3. Answer a small number of business-context questions.
4. Inspect prioritized, evidence-backed findings.
5. Confirm, dismiss, or investigate findings.
6. Review remediation advice and executable validation rules.
7. Export a Markdown report and JSON or YAML rules.

## Engineering principles

- Deterministic code calculates facts.
- AI interpretation cannot erase or replace deterministic findings.
- Every factual statement must resolve to computed evidence.
- Uploaded values, column names, worksheet names, and model responses are untrusted.
- Model responses are schema-validated before use.
- The complete application works with AI disabled.
- Local `llama.cpp` integration must not require an API key.
- Version 1 avoids unnecessary distributed infrastructure.

## Documentation map

### Product and architecture

- [Product requirements](docs/product-requirements.md)
- [Domain model](docs/domain-model.md)
- [Architecture](docs/architecture.md)
- [API specification](docs/api-specification.md)
- [Detector framework](docs/detector-framework.md)
- [UI specification](docs/ui-specification.md)
- [Security threat model](docs/security-threat-model.md)

### Delivery and quality

- [Install and run on Linux](docs/installation-linux.md)
- [Local development](docs/local-development.md)
- [Configuration](docs/configuration.md)
- [Implementation backlog](docs/implementation-backlog.md)
- [Testing strategy](docs/testing-strategy.md)
- [Release plan](docs/release-plan.md)
- [Engineering principles](docs/engineering-principles.md)
- [Decision log](docs/decision-log.md)

### Reviews and decisions

- [Engineering reviews](docs/reviews/)
- [Architecture Decision Records](docs/adr/)

### Project roles

- [Role handbook](agents/README.md)
- [Product Owner](agents/product-owner.md)
- [Software Architect](agents/software-architect.md)
- [Backend Lead](agents/backend-lead.md)
- [Frontend Lead](agents/frontend-lead.md)
- [AI and Data Science Lead](agents/ai-data-science-lead.md)
- [QA Lead](agents/qa-lead.md)
- [Coding Agent](agents/coding-agent.md)

## Planned technology

### Frontend

- React
- strict TypeScript
- Vite
- React Router Data Mode
- TanStack Query
- React Hook Form
- Tailwind CSS
- selective accessible UI primitives
- OpenAPI-generated API types
- Vitest, Testing Library, MSW, Playwright, and axe-core

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy 2
- Alembic
- SQLite
- pandas and NumPy
- openpyxl
- bounded in-process background work
- `llama.cpp`, disabled, and mock model providers

## Supported production boundary

Version 1 is a production-quality, local-first, single-instance application.

Formally supported development and deployment environments:

- Linux x86-64
- Windows 11 with WSL2 and Docker Desktop

Current Chrome, Edge, Firefox, and Safari are target browsers. Native Windows execution without WSL is not a version 1 requirement.

## License

Apache License 2.0.
