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
