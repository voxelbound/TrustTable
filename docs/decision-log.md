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

**Under review (2026-09-13, appended — does not alter the decision
above):** the `v0.2 — Local AI beta` design session (`CHG-002`)
reaffirmed local-only inference for v0.2 but explicitly reopened the
specific runtime choice — `llama.cpp` and Ollama remain live finalists,
pending a TrustTable-specific hands-on benchmark. This paragraph does
not supersede the decision above; it records that the decision is
under active review and must not be treated as reaffirmed until a
runtime decision is actually recorded. See `D-030`–`D-032` and
`project-ops/changes/CHG-002-v02-local-ai-design-outcome.md`.

**Still under review (2026-09-16, appended — the model decision below
does not resolve this):** `D-034` selects an exact model and
quantization for the baseline hardware profile. The runtime question
this entry names remains fully open — every hands-on evaluation round
to date used a benchmark-only `llama.cpp` adapter exclusively (never
the production provider integration, and never Ollama at all). This
runtime choice still must be made before `AI-03` can start.

**Resolved for v0.2 baseline scope (2026-09-16, appended — see `D-035`
for the full decision):** `llama.cpp` is selected as the v0.2 baseline
local-inference runtime. Ollama is recorded as a future alternative/
re-evaluation candidate, not disqualified. This is a bounded v0.2
implementation decision, not a universal claim of superiority.

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

## D-025 — Row-context exposure scoping

**Decision:** `FIND-01` row context may display full-row, all-column physical neighborhoods around a finding's affected rows, scoped to the local single-user deployment model — not Evidence, not in Report/export output by default, never automatic AI-prompt input. Hosted/shared deployment (D-008/D-009, HOST-DEC-01) must reassess before enabling it; `PRIV-01` must consider row-context in future redaction design.

## D-026 — v0.2 AI product scope

**Decision:** `v0.2 — Local AI beta` remains a bounded interpretive layer over TrustTable's existing deterministic workflow — context inference, finding explanations, remediation wording, report summaries, rule descriptions, and a small number of guided questions/suggested checks. No open-ended "chat with your dataset" feature, no autonomous agent exploring the dataset, no long chains of follow-up questions, no general user question box, and no requirement for the model to plan or execute arbitrary analytical queries.

**Reason:** v0.2's purpose is to prove local LLMs add real, reliable value on top of the already-working deterministic pipeline — not to become a general-purpose data chatbot or agent.

**Not foreclosed:** a future, richer questioning path (`user question → determine required evidence → query/calculate against dataset → build bounded context → model response → validation`) is architecturally compatible with the same trust boundary and may be built later; it is not exposed or implemented in v0.2.

## D-027 — Bounded LLM context vs. full deterministic analysis

**Decision:** Dataset size and model context window are separate concerns. TrustTable's deterministic pipeline may analyze datasets much larger than any model's context window; the deterministic analysis always covers the full dataset; the context builder supplies the model with only bounded, relevant summaries/evidence/findings — never the raw uploaded file.

**Working context-size guidance (design guidance, not a hard limit until benchmarked):** a typical model call targets roughly 4k–16k useful tokens; a heavier explanation/investigation call may reach roughly 32k. A model's maximum advertised context window is explicitly **not** a selection priority — structured-output reliability, instruction-following, groundedness, latency, and RAM/VRAM fit are weighted first.

**Clarification (2026-09-13, design review — narrows nothing above, makes an implicit distinction explicit):** "local-only" (`D-007`'s review scope) means **zero network egress during inference itself** — a hard, testable product guarantee — which is a distinct concern from *acquisition-time* network access (downloading a model during setup/onboarding, `D-031`), which is expected and normal. A future implementation should be able to demonstrate "no outbound network call occurs while an analysis is running with AI enabled" as an explicit, separately-testable claim, independent of how the model was obtained.

## D-028 — Excel/XLSX pragmatic scope (applies whenever `ING-03` is implemented, not `v0.2`)

**Decision:** Whenever XLSX support (`ING-03`) is implemented, it should mean reading sheets/tables/values and analyzing the tabular data through the same deterministic pipeline as CSV. Lightweight formula metadata (whether a cell contains a formula, the formula text, the displayed/cached value) is retained only where cheap and useful — e.g. to support an explanation noting a suspicious value is formula-derived.

**Explicitly deferred, not required unless separately justified later:** a formula recalculation engine, full dependency graphs, cross-sheet formula tracing, named-range dependency analysis, deep lookup-chain investigation, or Excel-compatible calculation semantics. These remain candidate future investigation features, not committed scope.

**Correction and resolution (2026-09-13, design review then human decision):** this entry was originally titled "v0.2 Excel/XLSX scope," which was inconsistent with the rest of the roadmap — `docs/implementation-backlog.md` places `ING-03` under the **Production completion / v1.0** group, and `docs/release-plan.md`'s own `v0.2` bullet list does not mention Excel/XLSX at all. The design review flagged this as an open, human-owned roadmap question rather than silently resolving it. **The human owner then explicitly decided: `ING-03`/XLSX support stays in its existing later roadmap position; it is not pulled into `v0.2`.** `v0.2` remains focused on proving the Local AI beta against the existing deterministic/tabular workflow, without adding a new ingestion subsystem to support the AI milestone. This entry now stands as confirmed milestone-agnostic *design* guidance for whenever `ING-03` is eventually implemented — not as v0.2 scope, and no longer an open question. See `project-ops/changes/CHG-002-v02-local-ai-design-outcome.md`.

## D-029 — v0.2 local-AI hardware profiles

**Decision:** Design and evaluate against two explicit local hardware profiles, not one:

- **Baseline business/evaluator profile:** CPU-only viable, no discrete GPU required; 16GB RAM minimum, 32GB RAM preferred; ordinary business applications (e.g. Outlook, Excel, browser tabs) may run concurrently; slower inference is acceptable but the product must remain functional.
- **Accelerated/developer profile:** Windows 11, RTX 3090 (24GB VRAM), Ryzen 9 5950X, 64GB system RAM — the same product capabilities, not a separate product; expected to support a larger and/or higher-quality model and materially better latency than the baseline profile.

**Reason:** TrustTable must remain practical to evaluate on an ordinary business machine while also supporting real hands-on experimentation on capable local developer hardware — without forking the product.

## D-030 — Model/runtime/inventory separation of concerns

**Decision:** Inference runtime/provider, model inventory, and active model selection are three independent architectural concerns. No specific model may be hardcoded into product logic. The architecture must support multiple local models, multiple quantizations of the same model, and models from different families simultaneously, with active-model switching that does not require an application-code change. A future business-facing model-selection UI (showing locally available models, model metadata, active model, and selection/download/register/remove actions) must remain architecturally possible, even though v0.2 ships with a simpler default experience.

**Reason:** Ties model choice to product logic would block both the developer's own hands-on experimentation goal and any future business-facing model choice.

**Clarification (2026-09-13, design review):** `v0.2` has no persistence layer yet (`DB-01` is a `v0.3` item). "Active model selection" in `v0.2` therefore cannot mean a user-persisted, runtime-switchable setting — there is nowhere to store that choice yet. In `v0.2`, active model selection is necessarily an operator/config-time setting, extending the existing `Settings.llm_provider`/`llm_model` pattern (`config.py`, `FND-02`). The richer, end-user-facing selection surface this decision anticipates remains correctly deferred until persistence exists. Implementation should also start from the simplest workable mechanism (e.g. a model path/identifier in configuration, as already anticipated in `project-ops/changes/CHG-001`'s own precedent) rather than building a full model-registry/plugin system before the benchmark (`D-032`) has demonstrated one is actually needed.

## D-031 — Model acquisition and licensing posture

**Decision:** Model weights are never committed to the Git source repository. An eventual packaged installer/onboarding flow is intended to acquire an approved model automatically and reproducibly (identify/select a suitable local model → download from an authoritative source → verify revision/checksum/license metadata → cache/store locally → ready to run). The human owner's own manual Hugging Face download, inspection, and comparison workflow remains fully available throughout design and initial implementation and is not automated away. Model licensing (local-use rights, commercial-use rights, redistribution rights, attribution/notice requirements, usage restrictions, compatibility with an open GitHub project and an eventual packaged business application) is a gating selection criterion, evaluated before quality comparison — TrustTable prefers not to redistribute model weights itself where that avoids unnecessary licensing/distribution complexity. (TrustTable's own repository is Apache 2.0 — confirmed by direct inspection of `LICENSE` during this design review — compatible on its own side with every model license discussed; a model under a non-OSI license with its own attribution terms, e.g. Meta's Llama community license's "Built with Llama" notice requirement, would still need that notice added to the shipped product if ever selected.)

**Required before automatic acquisition is implemented (2026-09-13, design review — a genuine gap, not yet resolved):** this decision names checksum/revision/license verification but does not yet specify (a) fail-closed vs. warn-and-continue behavior when verification fails, (b) whether download sources are pinned to a TrustTable-controlled allow-list or accept an arbitrary user/business-installer-supplied repository reference, or (c) that model-file parsers themselves (GGUF and others) are a real attack surface with prior CVE history, distinct from the model's own license terms. A `docs/security-threat-model.md` update covering automatic model acquisition specifically must happen before that feature is implemented — it is explicitly not required for this planning-only package, and is not yet done.

## D-032 — v0.2 AI model/runtime selection method

**Decision:** Runtime and model selection for v0.2 are made from a TrustTable-specific benchmark — fixed, versioned fixtures built from the real, already-merged `ai_boundary` trust-boundary contract (`PromptEnvelope`/`build_safe_prompt`/`validate_model_output`) exercised against the committed deterministic demo dataset — rather than from generic public model benchmarks (coding-agent leaderboards, general chat-quality rankings, etc.), which do not measure what this product actually needs.

**The benchmark harness itself is intended as a persistent, reusable, repository-resident evaluation capability:** config-driven model/runtime selection, fixed/versioned TrustTable-specific fixtures, reusable for future models and quantizations beyond v0.2. It is explicitly not product UI and not the production AI provider integration.

**Not yet decided by this entry:** the runtime, the model family, the exact model, and the exact quantization all remain open (see `D-007`'s appended review note and `project-ops/changes/CHG-002-v02-local-ai-design-outcome.md`'s "Explicitly NOT decided" section). The benchmark harness itself was implemented by `AI-06`/`WP-043` (2026-09-14) — see the appended note below; it has not yet been run against a real local model/runtime.

**Disclosed limitations (2026-09-13, design review):** the first-round fixture set is deliberately drawn from a single dataset (the committed `demo-data/sales_demo.csv`), matching the "small and reproducible" requirement — this is appropriate for a first bounded round, but a model selection based only on this file risks being fit to that file's own quirks; a second, distinct data source should corroborate any selection treated as final. The benchmark harness requires a real local model/runtime and is therefore **not** part of the standard CI-gated automated test suite — it must not be wired into CI the way `AI-02`'s deterministic mock-provider tests are; it follows the same release-candidate-only-gate precedent already established for this project's browser/performance test layers (`docs/testing-strategy.md` §8).

**Confirmed scoring boundary (2026-09-14, appended after `AI-06`/`WP-043`'s harness implementation, human-directed verification before merge):** the implemented harness measures structural output validity/groundedness (every evidence ID, column, and numeric claim checked against what was actually sent — via the already-merged `validate_model_output`), harness-measured latency, bounded retry rate, and repeated-call consistency. It does **not** score narrative/explanation *quality*, semantic correctness beyond grounding, or *category accuracy* — no field for any of these exists in the harness today, and no LLM-judge or human-review scoring step was added. No fixed numeric acceptance threshold (e.g. a latency ceiling, a memory ceiling, or a pass-rate percentage) for any metric is decided by this entry or by any other currently accepted decision — none of `D-029`, `D-030`, or this entry specifies one. If narrative-quality/category-accuracy scoring or specific numeric acceptance thresholds prove necessary before a final model-selection decision, that is future benchmark-design work requiring its own proposal and human approval (a new `CHG-00X`/decision entry), not something implied by or silently added to this decision.

**Persisted candidate/resource-evidence fields (2026-09-14, r3, appended after further human-directed pre-merge verification):** the persisted benchmark-result document (`persistence.save_report`/`load_report`) now carries an explicit `CandidateMetadata` (`runtime_identifier`, `model_identifier`, `hardware_profile` required; `quantization_identifier` nullable) and optional `ResourceObservations` (`peak_rss_mb`, `peak_vram_mb`), so the later hands-on comparison of runtime/model/quantization candidates does not depend on parsing free-form identifier strings. Both are caller-supplied for now — this revision adds no host-telemetry collection (no `psutil`, no GPU library, no subprocess probing, no automatic measurement of any kind) and no runtime/model/quantization selection. This is a structural/schema clarification of the already-accepted harness design, not a new decision; it introduces no numeric acceptance threshold.

**Benchmark-only real-runtime bridge added (2026-09-14, appended after `WP-044`, human-directed):** `ai_benchmark.adapters.llama_cpp_http.LlamaCppHttpProvider` now exists, giving the harness a way to reach a real, locally running `llama-server` over HTTP without implementing `AI-03`. It is evaluation tooling only — not registered in `ai_provider.factory`, not selectable via `Settings.llm_provider`, not reachable from any FastAPI route or application service. This entry's "has not yet been run against a real local model/runtime" statement above remains true: `WP-044` proves only the adapter's transport/parsing behavior against stubbed HTTP responses (`httpx.MockTransport`), the same non-live-model CI posture `AI-06`'s own tests already established. No runtime, model, or quantization is selected by this note or by `WP-044`; `AI-03` and the human decision gate remain exactly as open as before. This is a tooling-availability update, not a new decision.

## D-033 — v0.2 Local AI implementation sequencing

**Decision:** Canonical `v0.2` implementation order is `AI-02` (disabled/mock providers) → `AI-06` (persistent local-AI benchmark harness) → hands-on benchmark/model evaluation → human decision gate (runtime, model family/exact model, quantization, per-hardware-tier default) → `AI-03` (real local-inference provider) → `AI-04` (corresponding runtime/model documentation) → the remaining `v0.2` backlog items in their existing order (`CTX-01`, `CTX-02`, `CTX-03`, `API-02`, `AI-05`, `UI-02`, `EVAL-AI-01`, `REL-02`). `AI-03` must not be treated as ready before `AI-06` and the human decision gate are both complete.

**Reason:** `D-032` already establishes that runtime and model selection follow from `AI-06`'s benchmark results, not the reverse; this entry makes that dependency an explicit implementation-sequencing constraint rather than leaving it implicit — `AI-06` has no architectural dependency on `AI-03`'s real-provider implementation and can (and should) be built and run first.

**Classification:** planning alignment / sequencing correction, not a new design choice — no acceptance criteria, scope, or release outcome changes. The four human-owned decisions this gate exists to make (runtime, model family/exact model, quantization, per-hardware-tier default) remain exactly as open as `CHG-002` left them; see `D-007`'s appended review note and `D-030`–`D-032`. See `project-ops/changes/CHG-003-v02-sequencing-and-planning-alignment.md`.

**Partially resolved (2026-09-16, appended):** `D-034` resolves the model family/exact model, quantization, and baseline-hardware-tier-default portions of this gate's four named items. Runtime and the accelerated-hardware-tier default remain open. `AI-03` must still not start until both are resolved.

**Complete for v0.2 baseline scope (2026-09-16, appended — see `D-035`):** the runtime item is now also resolved (`llama.cpp`). All four named items are decided for v0.2 baseline scope; `AI-03` is ready to start, scoped to the baseline/CPU-oriented profile. The accelerated/GPU hardware-tier default remains explicitly deferred by deliberate human choice — a later, non-blocking follow-on, not an unresolved gap in this gate's baseline-scope completion.

**Sequencing amendment (2026-09-17, appended — see `D-036`):** `AI-07` (llama-server runtime hardening: WebUI disabled, dedicated port) is inserted into the canonical order immediately after `API-02` and before `AI-05`. Updated order for the remaining items: `CTX-01` → `CTX-02` → `CTX-03` → `API-02` → **`AI-07`** → `AI-05` → `UI-02` → `EVAL-AI-01` → `REL-02`. This is a small, self-contained runtime-hardening correction with no dependency on `AI-05`/`CTX-0x`; it does not reopen any decision this entry or `D-034`/`D-035` already settled.

## D-034 — v0.2 baseline-profile model selection: Qwen3.5-4B-Q4_K_M

**Decision:** Qwen3.5-4B-Q4_K_M is selected as the CPU-oriented/default TrustTable model (`D-029`'s baseline business/evaluator hardware profile). Qwen3.5-9B-Q4_K_M is retained, not disqualified, as a documented higher-capacity reevaluation/escalation candidate, to be revisited only if a future, product-realistic workload demonstrates a concrete capability limit in Qwen3.5-4B that Qwen3.5-9B is shown to resolve. This is a bounded product decision for the evaluated candidates and hardware profile — not a claim that Qwen3.5-4B is universally better than Qwen3.5-9B.

**Basis:** across three independent hands-on evaluation rounds (structural screening, a blind qualitative comparison, and a controlled performance/resource comparison — full detail in `docs/evaluation/ai-06-first-round-model-screening-2026-09-16.md`), both candidates were structurally identical (6/6 accepted outputs, zero provider errors, identical retry behavior, every round). The blind qualitative comparison was close and mixed and did not establish a consistent output-quality advantage for either candidate. The controlled performance/resource comparison (host confirmed idle/reserved before measurement) showed Qwen3.5-9B costs roughly 30–50% more aggregate latency and roughly 50–60% more peak working-set memory than Qwen3.5-4B. No TrustTable-specific evidence demonstrates a product-relevant capability advantage for Qwen3.5-9B that justifies that additional cost as the default.

**Explicit scope — resolved:** model family and exact model (Qwen3.5-4B) and the baseline/CPU-oriented hardware-tier default. Q4_K_M is recorded as the selected baseline quantization because it is the quantization the selected model was evaluated and chosen at — **no comparative quantization study was performed**; this decision does not claim Q4_K_M was evaluated against or shown superior to any other quantization.

**Explicit scope — not resolved:** the runtime (`D-007`; `llama.cpp` and Ollama remain finalists — every evaluation round used a benchmark-only `llama.cpp` adapter, never the production integration and never Ollama) and the accelerated/developer hardware-tier default (`D-029`'s second named profile was never evaluated — every round ran CPU-only). `AI-03` must not start until both remaining items are resolved (`D-033`).

**Standing instruction:** the model benchmark (all three rounds) is not to be re-run absent a genuinely new product requirement creating new evidence needs.

**Update (2026-09-16):** the runtime item this entry left "not resolved" is now decided — see `D-035`.

## D-035 — v0.2 runtime selection (llama.cpp), AI-06 gate closure, AI-03 readiness

**Decision:** `llama.cpp` is selected as the v0.2 baseline local-inference runtime. Ollama is recorded as a future alternative/re-evaluation candidate — not disqualified, not a co-equal blocker. This is a bounded v0.2 implementation decision, not a universal claim that `llama.cpp` is superior to Ollama.

**Basis:** every hands-on evaluation round completed for this project (first-round screening, blind qualitative comparison, controlled performance/resource comparison) used `llama.cpp` successfully via its benchmark-only adapter, exercised repeatedly against the selected model (`D-034`); Ollama has not been evaluated in this project at all; a fresh runtime benchmark is not required merely to preserve an historical two-finalist framing.

**Gate closure:** combined with `D-034`, this decision resolves all four items named by `docs/implementation-backlog.md`'s "Human decision gate" **for v0.2 baseline scope**: model family/exact model (Qwen3.5-4B), quantization (Q4_K_M, recorded as evaluated — not comparatively selected), runtime (`llama.cpp`), and the baseline/CPU-oriented hardware-tier default. The "hands-on AI-06 evaluation" phase closes in full.

**`AI-03` is now ready to start**, scoped to: a real `llama.cpp` local-inference provider for Qwen3.5-4B-Q4_K_M on the baseline/CPU-oriented hardware profile. `AI-03` implementation itself remains a separate, later package — not started or implemented by this decision.

**Explicitly deferred, non-blocking:** the accelerated/developer (GPU) hardware-tier default (`D-029`'s second named profile). This is a deliberate scoping choice, not an unresolved gap — it may be evaluated later, once the real provider path exists and there is an actual product need for a separate default.

**Standing instructions (unchanged from `D-034`):** the model benchmark is not to be re-run absent a genuinely new product requirement. No runtime head-to-head benchmark and no quantization benchmark were performed or are required by this decision.

**`AI-03` implemented (2026-09-16, appended — no decision text altered):** `ai_provider.llama_cpp.LlamaCppProvider` is now the real, product-registered `AIProvider` for `llm_provider="llama_cpp"`, structurally mirroring the already-proven benchmark-only adapter (`WP-044`). `Settings.LlmProvider`'s literal values are now `"disabled" | "mock" | "llama_cpp"`; `Settings.llm_provider`'s default remains `"disabled"`. No FastAPI route, application service, or analysis-pipeline calls this provider yet — that remains `CTX-01`/`CTX-02`/`CTX-03`, separate later packages. No accelerated/GPU hardware-tier work was done.

## D-036 — llama-server runtime hardening: infrastructure-only, WebUI disabled, dedicated port

**Decision:** `llama.cpp`'s `llama-server` is treated strictly as inference infrastructure, never a user-facing application. TrustTable remains the sole user-facing surface. The documented and supported TrustTable runtime profile starts `llama-server` with its built-in Web UI disabled (`--no-webui`), and the documented local baseline moves `llama-server` to host port `8081`, distinct from TrustTable's own frontend port (`8080`), to eliminate a real host-port collision when both run locally at once.

**Basis:** `llama.cpp`'s `tools/server/README.md` (`ggml-org/llama.cpp@master`, checked directly against the current upstream documentation before this decision, not delegated) confirms the server ships a Web UI **enabled by default** (`--ui, --webui, --no-ui, --no-webui` — "whether to enable the Web UI (default: enabled)"). TrustTable's existing local-development guide (`AI-04`, `WP-055`) instructed starting `llama-server --port 8080` with no `--no-webui` flag, which (a) would leave an unintended, unreviewed, undocumented user-facing UI reachable alongside TrustTable's own frontend, and (b) collides on host port `8080` with the TrustTable frontend `docker-compose.yml` already publishes there. Disabling the Web UI also removes exposure to its default-enabled experimental MCP proxy and server-side filesystem tool-calling features, which are otherwise reachable only through that same UI — a secondary, not independently sought, security-positive effect of this decision, not a new requirement.

**Scope — what this decision changes:**
- The documented/supported `llama-server` startup command gains `--no-webui` and moves from `--port 8080` to `--port 8081`.
- `LLM_BASE_URL`'s documented example and default value (Docker→host) change from `http://host.docker.internal:8080` to `http://host.docker.internal:8081`.
- TrustTable's own frontend port (`8080`) is unchanged.

**Explicit non-scope — what this decision does not change:** this is not a model-selection or runtime-selection change and does **not** reopen `D-034` (exact model: Qwen3.5-4B-Q4_K_M) or `D-035` (runtime: `llama.cpp`, baseline/CPU-oriented profile). No new llama.cpp UI, agent, chat-history, or other user-facing functionality is introduced by this decision or its implementation — the change is a runtime-profile/default-configuration-value correction only.

**Sequencing:** inserted into the canonical `v0.2` sequence (`D-033`) as `AI-07`, immediately after `API-02` and before `AI-05` — see `D-033`'s own appended annotation and `docs/implementation-backlog.md`. This ordering was chosen because it is a small, self-contained runtime-hardening correction with no dependency on `AI-05`/`CTX-0x` and no reason to defer it past the point it was identified.

**Decided by:** human owner, explicit instruction, 2026-09-17.

## D-037 — v0.2 two-phase context/AI model: non-blocking deterministic baseline plus additive enrichment

**Decision:** `v0.2` adopts, as its approved target architecture, context confirmation and AI-assisted interpretation as a second, optional **enrichment phase** layered over an already-`COMPLETED` deterministic analysis, not as a blocking step inside the deterministic pipeline. This decision does not itself implement any route, UI, or new domain type (see "Explicit non-scope" below) — it fixes the architecture the real `UI-02` implementation package builds against. The deterministic pipeline (`API-01`'s `run_analysis`) keeps its current, already-shipped shape unchanged: `QUEUED → ... → DETECTING → COMPLETED`, with no `inferring_context`/`awaiting_confirmation`/`finalizing` pause. `docs/domain-model.md` §5's fuller 11-value `States` list (including those three) remains the documented shape for a possible future **pre-analysis context-gating** architecture (see "Explicitly not foreclosed" below) — it is not implemented by `v0.2`, and `AnalysisState`'s real 8-value enum (`analysis/service.py`, `API-01`/`API-02`) is the authoritative shipped state set for this milestone.

Enrichment (context confirmation, guided questions, and validated AI interpretation/explanations) must be:

- **optional** — a `COMPLETED` analysis is fully valid, reviewable, and exportable with zero enrichment; deterministic findings, evidence, and the trust score never require it (`docs/domain-model.md` §8's existing "context does not alter historic deterministic profile facts" invariant, unchanged);
- **additive and distinguishable** — enrichment output is stored as its own record type, referenced from (not substituted for) the deterministic `Finding`/`DatasetContext` it augments, and is never silently merged into deterministic fields;
- **exposed through real API routes**, not left as a disconnected backend-only enabling slice — the real implementation package must wire `API-02`'s already-built service methods (`get_or_infer_context`, `confirm_context_fields`, `answer_guided_question`, `finalize_context`) and `AI-05`'s already-built explanation builders (`build_deterministic_explanation`, `build_finding_explanation_envelope`/`run_finding_explanation`) to actual FastAPI routes and a real UI interaction, not merely extend the enabling-slice pattern further.

**Reconciling the already-specified `AIInterpretation` type:** `docs/domain-model.md` §14 already specifies a full `AIInterpretation` record (provider, model, prompt version, input evidence IDs, untrusted-data exposure summary, validated output, validation result, rejected reason, fallback used) and §12 already reserves a `Finding.interpretation ID` field pointing to it — this is the already-designed shape for exactly the "additive and distinguishable" enrichment this decision requires. `AI-05` (`WP-061`)'s `domain.explanation.FindingExplanation` is a narrower, ad-hoc interim shape (narrative, provenance, grounding references only — no provider/model/timing/rejection-audit fields, no `Finding.interpretation ID` link) built before this decision existed. This is a disclosed, known gap: the real `UI-02` implementation package must reconcile `FindingExplanation` toward (or replace it with) the fuller `AIInterpretation` shape rather than silently building a second, permanently-divergent type. This does not reopen or invalidate `WP-061`'s already-merged, already-tested code; it schedules its convergence.

**`POST /finalize` (`docs/api-specification.md` §9) clarified:** "finalize" ends the *context-confirmation* sub-flow (guided questions answered/context fields confirmed or left explicitly unknown) and triggers **enrichment** — validated AI interpretation/explanations grounded in the confirmed context and the existing deterministic evidence — not "context-dependent analysis" in the sense of re-running or gating deterministic detection. The response remains `202 Accepted` plus an updated resource, but that resource is the enrichment result, layered over the unchanged, already-`COMPLETED` deterministic analysis — never a transition of the deterministic analysis's own `AnalysisState`.

**Explicitly not foreclosed:** true pre-analysis context gating (`docs/domain-model.md` §5's full state list; `docs/architecture.md` §6's original single-pipeline diagram; contextual/context-dependent detectors, referenced but never scheduled in `docs/domain-model.md` §8's "context-dependent detectors record the context version used" invariant and `docs/detector-framework.md`) remains a legitimate, intentional future architecture decision — for example if `v0.3`'s rule engine (`RULE-01`/`RULE-02`) or a later detector genuinely requires confirmed context before it can run safely. That decision, if and when it becomes necessary, requires its own human-owned strategic decision; this entry does not decide it now and does not make it structurally impossible later (the reserved `AnalysisState` values and the original pipeline diagram are preserved in `docs/domain-model.md`/`docs/architecture.md`, annotated as the future shape rather than deleted).

**Explicit non-scope:** this decision does not itself implement any route, UI, or new domain type — see `docs/implementation-backlog.md`'s `UI-02` entry for the resulting implementation scope. It does not reopen `D-033`'s sequencing, `D-034`/`D-035` (model/runtime), or `D-036` (runtime hardening).

**Basis / provenance:** identified while scoping `UI-02` (the literal `docs/api-specification.md` §9 spec and the currently-shipped non-blocking pipeline are mutually inconsistent — `API-02`/`WP-059` had already disclosed this exact gap without resolving it); three candidate directions were considered (a full pipeline-pause architecture, a minimal non-blocking formalization, and a narrowly-scoped AI-explanation-only slice); resolved by explicit human direction specifying this two-phase model with the constraints captured above, rather than adopting any single candidate as originally framed.

**Decided by:** human owner, explicit instruction, 2026-09-17.

**Closure verified and corrected before merge (2026-09-18, appended — no decision text altered):** the human owner independently verified `UI-02`'s first implementation attempt (`WP-063`/`WP-064`, PR #60, pre-merge) against this entry's own text and found it insufficient — `GET .../context` never called CTX-02 regardless of provider configuration, and the explanation route never used confirmed/finalized context, leaving the two features structurally disconnected exactly as this entry warned against ("not merely extend the enabling-slice pattern further"). Corrected in the same PR before merge: `GET .../context` now calls `context_inference.ai_context.run_context_inference` through the real provider factory on an analysis's first inference only (never re-invoked once cached — a bounded, "compute once" scope, not a per-request live call), persisting an accepted AI-sourced `probable_domain` via a new `analysis.service.apply_ai_context_augmentation` (still no `ai_boundary`/`ai_provider` import in `analysis/service.py` itself — the route layer computes the augmented context, the service function only persists the value it is handed). `GET .../findings/{finding_id}/explanation`'s envelope now carries the finalized `DatasetContext` as `confirmed_context` once `POST .../finalize` has been called — gated specifically on `context_finalized`, not merely `context is not None`, so `finalize` is the real, observable trigger for context-grounded enrichment this entry names, while every pre-finalize call keeps its exact `WP-063` behavior (evidence-grounded only). `finalize_context`'s own service-layer behavior (marks `context_finalized`, no synchronous fan-out AI call across every finding) is unchanged — the "enable" reading of "finalize triggers enrichment," not a requirement that finalize itself synchronously generates every explanation. Real end-to-end tests (not merely unit-level) prove the actual request an `AIProvider` receives carries `confirmed_context` only after finalize, and that the real provider is called at most once per analysis for context inference.

## D-038 — AI exposure/provenance disclosure semantics: deterministic-pipeline exposure vs. per-request enrichment calls are always distinct signals

**Decision:** Every screen, API field, and document that discloses AI-related exposure or provenance must distinguish, and must never conflate, at least these six axes:

1. **provider configured** — whether `Settings.llm_provider != "disabled"` for the deployment;
2. **AI call attempted** — whether a provider was actually invoked for *this specific request*;
3. **accepted / rejected / provider-error fallback** — the outcome of that specific attempt;
4. **raw/flagged dataset-sample exposure** — whether a finding's own raw, potentially-suspicious dataset value was itself transmitted to a model (`Analysis.security_exposure`/`SecurityExposureState`'s exact, narrow scope — permanently `False` today because no detector ever does this);
5. **finding/evidence/context metadata exposure** — whether bounded, already-computed `Evidence`/`DatasetContext` was sent to a model as part of an optional enrichment call (`AI-05`/`UI-02`'s explanation/context routes);
6. **provider/model identity** — which provider and model, if any, produced an accepted output.

Axis 4 (`Analysis.security_exposure`, `PromptInjectionWarning`'s "sent to model"/"model location"/"rejected-output status") and axes 1–3/5/6 (a per-request AI enrichment call's own `ai_call_status`/`provenance`/`provider_name`/`model_identifier`) are **structurally independent signals with different scopes** — the first describes the deterministic detection pipeline's own posture at finding-generation time; the second describes a separate, optional, later call that never touches the first. Neither may be derived from, silently synchronized with, or presented as if it were the other.

**Basis / provenance:** discovered by the human owner during manual end-to-end testing against a real local `llama.cpp` runtime (2026-09-18): the Finding Detail screen simultaneously showed an accepted AI-generated explanation (`"AI interpretation — llama_cpp (...)"`) and multiple "no AI was used" claims (`PromptInjectionWarning`'s fields, Technical metadata's generic "AI model enabled" row) for the same finding. Root-caused to `FindingDetailRoute.tsx`/`PromptInjectionWarning.tsx` reusing `finding.security_exposure` (axis 4, deliberately and correctly always `False`) under generic wording that read as a blanket claim about axes 1–3 (the separately-configured, independently-driven enrichment call). Both underlying signals were individually correct; only the presentation conflated their scope. Corrected by `WP-065` (defect fix): a new `FindingExplanationResponse.ai_call_status` field disclosing axes 2–3 explicitly, removal of the misleading generic Technical-metadata row, reworded `PromptInjectionWarning` copy making axis 4's narrow scope explicit, and corrected stale documentation (`docs/architecture.md` §3/§6, `docs/api-specification.md` §9/§13) that had claimed no route called a provider after `UI-02` (`WP-063`/`WP-064`) had already shipped routes that do.

**Explicit non-scope:** does not reopen `D-034`/`D-035` (baseline model `Qwen3.5-4B-Q4_K_M`, runtime `llama.cpp`) — the manual test that surfaced this defect used `Qwen3.5-9B` locally, which is not adopted as any baseline change by this decision. Does not implement the full `docs/domain-model.md` §14 `AIInterpretation` shape (interpretation ID, schema version, prompt version, untrusted-data exposure summary, timing/token metadata, persistence) — that reconciliation, already disclosed as open in `D-037`, remains a separate, later package.

**Decided by:** human owner, explicit instruction, 2026-09-18.

**Independent review finding and correction (2026-09-19, appended — no decision text altered):** an independent fresh-context review of `WP-065` (revision 3, `reviewed_head` `1ccef93`) found this entry's own six-axis intent not yet satisfied, for two concrete reasons, neither hypothetical: (1) axis 5 ("finding/evidence/context metadata exposure") was defined as required but appeared in no response field and no rendered label anywhere in the initial implementation — `ai_call_status` alone discloses axes 1–3/6, never what was actually sent; (2) `PromptInjectionWarning`'s "Model location" field, when `security_exposure.model_provider_enabled` is `False` (always, today), rendered "No AI model is configured for this exposure path" — wording a reviewer correctly identified as still readable as a blanket "no AI is configured" claim when a real provider is in fact configured and producing an accepted explanation elsewhere on the same screen, and the existing combined-scenario frontend test's negative regexes did not actually assert against that string. Corrected in the same package before delivery-ready: `FindingExplanationResponse` gains `evidence_sent_to_model`/`confirmed_context_sent_to_model` (both derived independently of `ai_call_status`, both `False` when no attempt was made, `evidence_sent_to_model` `True` on every attempt, `confirmed_context_sent_to_model` additionally `True` only once `context_finalized`), rendered as an explicit, distinct line in the Finding Detail Explanation section whenever an attempt was made; `PromptInjectionWarning`'s "Model location" text changed to "Not applicable for this exposure path" (removing the ambiguous "configured" framing entirely for the always-`False` case); the combined-scenario frontend test extended to assert against the actual rendered `PromptInjectionWarning` text, not only `FindingDetailRoute`'s own strings. A second fresh-context review, bound to the corrected revision/HEAD, is required before delivery-ready per this project's own semantic-review gate — no completion is claimed here pending that PASS.

**Second semantic review FAIL and real data-flow correction (2026-09-19, appended — no prior text altered):** the second fresh-context review found a genuine, pre-existing trust-boundary violation, not another labeling gap, and it was independently re-verified against the actual code before acceptance: `detectors.security.PossiblePromptInjectionDetector` (`DET-SEC-01`) carries `truncated_sample_prefix` — an up-to-80-character literal excerpt of a finding's actual flagged raw cell value, a legitimate local field (`docs/domain-model.md` §15, `docs/security-threat-model.md` §5) the frontend deliberately never renders, pending `PRIV-01` — on its `SECURITY_PATTERN` evidence's `structured_payload`. `ai_boundary.prompt._serialize_evidence` (`SEC-02`) forwarded `structured_payload` unfiltered into the AI-bound `computed_evidence` payload every real `AIProvider` implementation sends, meaning a configured provider genuinely received this raw excerpt when explaining an `ai_processing_security` finding — present since `AI-05`/`WP-061`, unrelated to and predating this package's own labeling work, but contradicting `SEC-02`'s own "untrusted content is data, never sent as `computed_evidence`" trust-boundary invariant and this very entry's original axis-4 wording ("permanently `False` today because no detector ever does this" / PromptInjectionWarning's "never itself sent to any model"). Per this project's semantic-review failure budget (two `FAIL`s escalate to the human), automation stopped and the finding, with options, was presented to the human owner, who directed a bounded fix (not a split into a separate package): `ai_boundary.prompt._serialize_evidence` — the single universal serialization seam every real provider calls through — now redacts `truncated_sample_prefix` specifically for `SECURITY_PATTERN` evidence from the AI-bound copy only; `detectors.security.py` and the canonical local `Evidence` object are unchanged (zero diff, grep-verified); the raw excerpt is withheld entirely, not relocated into `untrusted_dataset_samples` under a different label. Proven with a real-provider-request-capture test (`httpx.MockTransport` against the actual `LlamaCppProvider`, not a stub) asserting the raw excerpt appears nowhere in the full outgoing HTTP request bytes while bounded non-raw metadata (e.g. `matched_pattern_categories`) remains present and an accepted explanation is still produced from the sanitized evidence, plus a white-box test proving the canonical local `Evidence` retains its own unmutated `truncated_sample_prefix`. Axis 4's wording above is accordingly corrected by this fix becoming true of it, not by softening the claim.

## D-039 — Model-output claim screen: unsupported whole-dataset claims and instructions to disregard deterministic results are rejected

**Decision:** `SEC-02`'s model-output validator (`ai_boundary.validation.validate_model_output`) rejects, with a new closed reason `unsupported_claim`, any otherwise schema-valid narrative that asserts an unsupported whole-dataset claim or tells the user to disregard deterministic results. It does so through a bounded, closed, documented lexical screen (`ai_boundary/claim_screen.py`, `CLAIM_SCREEN_VERSION` `"1"`) over five claim families:

1. `dataset_perfection_claim` — a dataset-level subject asserted perfect, clean, valid, accurate, reliable, and similar ("this dataset is perfect", "the data is completely clean");
2. `no_issues_claim` — an assertion that no data-quality issues exist ("no data quality issues were found", "the data is free of errors");
3. `disregard_findings_instruction` — an instruction or assurance to ignore, dismiss or override findings, scores, risk or evidence ("you can ignore the findings", "nothing to worry about");
4. `score_override_claim` — a trust/quality score asserted perfect or maximal, or risk asserted zero;
5. `fitness_assurance_claim` — an assurance that the dataset is safe to use or trust.

The screen runs inside the single validator seam, so it applies uniformly to every `AIOperation` (finding explanation, context inference, and the benchmark harness). Only the reason code is ever recorded or fed back to a provider as retry feedback — never the narrative text.

**Basis:** the prompt-injection adversarial evaluation (`EVAL-AI-01`, `docs/testing-strategy.md` §3: "unsupported 'dataset is perfect' output is rejected") found that the validator was purely structural — it checked schema, evidence IDs, column names, numeric claims, severity, provenance and unsupported control fields, but never what a narrative *says*. A schema-valid output whose only content was "this dataset is perfect" would have been accepted and shown to the user as an AI interpretation beside findings that contradict it, including when it cited genuine evidence IDs. The earlier adversarial mock cases were rejected only because they also fabricated an evidence ID or added a control field, not because the claim itself was detected. Deterministic authority was never at risk (no output field can remove a finding or change a score, and explanation grounding comes from the evidence actually sent) — the exposure was a false narrative being *presented* as an accepted interpretation.

**Alternatives considered:** (a) a grounding-only gate requiring accepted outputs to cite a known evidence ID — purely structural, but a false claim that cites a real ID would still pass, and it needs per-operation rules; (b) keeping the validator structural and rewording the acceptance criterion — smallest change, but leaves the exact scenario unmitigated; (c) replacing free-prose narratives with a constrained, templated output — the strongest long-term guarantee, but a large output-contract change across explanation, context inference and the UI, reopening shipped behavior. The bounded screen is the only option that rejects a narrative-only claim regardless of what it cites, is additive and removable, and follows the bounded-lexical precedent already set by the prompt-injection detector (`D-015`). It does not foreclose (c) as a later step.

**Posture and documented limits:** the screen is defense in depth, not the guarantee — deterministic authority remains the guarantee. It is deliberately **biased toward rejecting**: a false positive degrades safely to the always-available deterministic explanation (`docs/product-requirements.md` §5.7), whereas a false negative is the real risk. It is lexical, English-only, does not fold cross-script homoglyphs, and a sufficiently creative paraphrase can evade it; it makes no claim of semantic completeness. The screen recognizes a *class* of claims rather than a list of phrasings: fixed patterns cover distinctive shapes, and a token-window matcher covers the open-ended part — a whole-dataset subject (`dataset`, `data`, `file`, `all rows`, `every record`, …) linked by a copula or preposition to a positive assessment within a short window — so "is in perfect condition", "is of excellent quality", "all rows are valid" and the inverted "not only is the dataset perfect" are all rejected; this is proven over a cross product of subjects, linking frames and adjectives, not only listed examples. Negation is honored only where it sits between the subject and the positive word or is adjacent to the claim ("is not perfect", "do not ignore the findings" pass; a stray "not" elsewhere, or a cheap hedge such as "in some sense", does not exempt a claim), while honest hedges ("only partly clean") and column scoping ("the data in the quantity column is valid") do stop the match. The "no issues" family is deliberately subject-free and verb-free — the claim is recognized whoever asserts it and in any grammatical shape (passive "no issues were found", active "the analysis found no issues", negated detection "did not find any issues", "without/free of"), with "no *other* issues" and column-scoped statements exempt; and "passes/meets all checks, tests, standards or rules" is recognized as an assurance. Class-level proof covers a cross product of actors × detection verbs × issue nouns × tails (active and negated-detection forms) and of subjects × passing verbs × check objects, with honestly hedged, negated and column-scoped counterparts accepted. Two limits are asserted in the tests so they stay honest: a hedged denial such as "this does not mean the dataset is perfect" is still rejected (the cost of not letting a leading "not" exempt a claim — a safe fall back to the deterministic explanation), and a creative paraphrase with none of the recognized shapes can still evade the screen. Deliberate exclusions, each covered by a negative-control test: "ignore previous instructions" phrasing (so an explanation that merely names a flagged injection pattern is not rejected — that content belongs to the prompt-injection detector); a *priority* score of 100 (the worst case, not a reassurance); and a "no issues" statement explicitly scoped to a named column. The whole narrative is screened with only bounded quantifiers, so padding a claim past a length cap cannot evade it and matching stays linear. Extending the screen means adding a family or pattern with a positive and a negative-control test and bumping `CLAIM_SCREEN_VERSION`.

**Where the protection is recorded (v0.2):** on the surfaces that exist before an exported report does — the explanation response's `ai_call_status` (`attempted_rejected`, with the deterministic explanation returned unchanged) and `evidence_sent_to_model` (`D-038`), and the Finding Detail "Protections in place" list. The exported report and its security section are v0.3 deliverables (`docs/release-plan.md`); asserting the applied protections there is tracked as a follow-up for that package, not claimed here.

**Explicit non-scope:** does not reopen `D-034`/`D-035` (baseline model and runtime), `D-037` (two-phase context/AI architecture) or `D-038` (disclosure semantics). Does not change detectors, risk scoring, `Analysis.security_exposure`, `AnalysisState`, any provider, any API route or response schema.

**Decided by:** the product intent — an adversarial response must not be able to produce an accepted AI interpretation that makes unsupported whole-dataset claims or tells the user to disregard deterministic findings or risk, with deterministic findings, evidence, severity and risk remaining authoritative and the existing graceful fallback preserved — was set by the human owner, 2026-09-19. The technical mechanism above was selected under delegated implementation authority and was not chosen by the human owner.
