# AI-06 first-round model screening (2026-09-16)

**Status: evidence record only.** This document publishes the results of
an already-completed hands-on evaluation round. It does not select a
runtime, model, or quantization; it does not close the "hands-on AI-06
evaluation" phase; and it does not start `AI-03`. All numbers below are
transcribed directly from the persisted benchmark result documents
produced by the governed evaluation runs named in "Provenance" — they
are not reconstructed from memory or summary text.

## 1. Purpose and project context

`docs/decision-log.md` D-032 establishes that TrustTable's `v0.2` local
AI runtime/model/quantization selection is made from a
TrustTable-specific benchmark — fixed, versioned fixtures built from the
real, already-merged `ai_boundary` trust-boundary contract
(`PromptEnvelope`/`build_safe_prompt`/`validate_model_output`), exercised
against the committed deterministic demo dataset — rather than from
generic public model-quality leaderboards, which do not measure what
this product actually needs (structured-output validity, groundedness
against supplied evidence, and safe behavior under this product's own
trust boundary).

D-033 fixes the implementation order: `AI-02` (disabled/mock providers)
→ `AI-06` (the benchmark harness itself) → **hands-on benchmark/model
evaluation** → the human-owned decision gate (runtime, model
family/exact model, quantization, per-hardware-tier default) → `AI-03`
(the real local-inference provider). `AI-06` (the harness) was completed
and merged (`WP-043`/`WP-044`/`WP-045`). This document is evidence
produced *inside* the still-open "hands-on benchmark/model evaluation"
step — it is a screening round, not the decision itself.

## 2. Candidates

Six candidates, drawn from the first-round shortlist agreed during
design (`docs/decision-log.md` D-032):

| # | Candidate |
|---|---|
| 1 | Qwen3.5-4B-Q4_K_M |
| 2 | Granite-4.2-3B-Q4_K_M |
| 3 | Ministral-3-3B-Instruct-Q4_K_M |
| 4 | Qwen3.5-9B-Q4_K_M |
| 5 | Granite-4.2-8B-Q4_K_M |
| 6 | Gemma-4-E4B-it-Q4_K_M |

## 3. Candidate-selection rationale and scope

This section explains, from durable project records only, why these six
candidates were chosen for the first round and what the round
intentionally did not attempt — for an independent reader who might
reasonably ask "why these models, and why not model X or Y?" No new
reasoning is invented here beyond what the cited sources actually state;
where the durable record does not explain something, this section says
so plainly rather than supplying a plausible-sounding reason.

### Selection principles

1. **Local-first.** TrustTable's AI use is local-only by design intent
   (`docs/decision-log.md` D-006 — complete AI-disabled mode, no paid
   dependency; D-007 — the specific runtime is under review, but
   local-only inference itself was reaffirmed for `v0.2`, per D-007's
   own appended review note). The first screening round
   targeted models that could be evaluated fully locally rather than
   depending on a paid or cloud inference API.
2. **A targeted engineering screening, not an exhaustive model
   leaderboard.** `D-032` explicitly chose a TrustTable-specific
   benchmark — fixed fixtures built from this product's own
   trust-boundary contract — over generic public model-quality
   leaderboards, because those do not measure what this product
   actually needs (structured-output validity, groundedness,
   latency/RAM/VRAM fit). The six-candidate round is sized accordingly:
   enough to compare real behavior differences, not an attempt to
   survey the broader model landscape.
3. **Sizing targeted practical deployment tiers.** `D-029` defines two
   explicit hardware profiles — a CPU-only baseline business/evaluator
   profile (16GB RAM minimum) and a GPU-accelerated developer profile.
   The executed candidates (3B–9B parameters) are sized toward the
   CPU-oriented baseline tier rather than beginning with very large,
   accelerated-only models.
4. **`Q4_K_M` as the common first-round quantization.** Earlier design
   work recorded that recommended first-round quantizations were noted
   for planning purposes only, in materials not committed as a
   separate durable artifact in this repository, so this report does not claim a
   documented per-model quantization rationale beyond what is directly
   observable: all six executed candidates used `Q4_K_M` uniformly,
   giving every candidate a consistent initial quantization for
   comparison.
5. **Multiple families, and multiple sizes within a family, on
   purpose.** The shortlist spans three model families (Qwen3.5,
   Granite 4.2, Ministral 3 — `Ministral-3-3B-Instruct`) plus a
   conditionally-included fourth (Gemma 4), and includes two sizes each
   of Qwen3.5 (4B/9B) and Granite 4.2 (3B/8B). This is consistent with
   `D-032`'s benchmark dimensions (structured-output validity,
   groundedness, latency) and is borne out by the actual results (§8):
   candidates of similar size behaved very differently (Ministral-3-3B-
   Instruct's 0/6 vs. Granite-4.2-3B's 3/6), and the same family showed
   a size-related quality shift (Qwen3.5-4B and -9B both reached 6/6,
   while Granite 4.2's 3B and 8B sizes diverged in validity, 0.5 vs.
   0.833) — the round was designed to expose exactly this kind of
   contract/instruction-following and grounding difference, not merely
   to rank parameter counts.
6. **No candidate-specific special treatment.** Every candidate ran
   under the identical frozen protocol described in §4 — no
   candidate-specific prompt tuning, parser relaxation, or other
   adjustment was introduced to improve any candidate's result,
   including for candidates that ultimately performed poorly
   (Ministral-3-3B-Instruct, Granite-4.2-3B).
7. **Absence is not the same as rejection.** A model not included in
   this first round is not thereby described as evaluated and rejected.
   Where the durable record does not give a reason for a candidate's
   absence, this section says so explicitly rather than supplying one.

### Considered but not part of this first round

Earlier internal design work that produced this shortlist recorded the
following:

> "A first-round hands-on benchmark shortlist was agreed (Qwen3.5, IBM
> Granite 4.2, Ministral 3, Phi-4-mini-instruct as primaries; Qwen2.5
> and Llama 3.x as optional controls; Gemma 4 conditional on
> independently verifying the actual weight-file download, not just the
> model card, is ungated; Qwen3.8, Ornith, and dedicated reasoning-mode
> variants deferred to a second round)."

Of the models named there, three different situations apply to what was
actually executed:

- **Explicitly deferred, not omitted without reason:** Qwen3.8, Ornith,
  and dedicated reasoning-mode variants were durably and explicitly
  deferred to a second round at design time. Their absence from this
  first round is documented design intent, not an unexplained gap.
- **Named as primaries or controls, absent without a documented
  reason:** Phi-4-mini-instruct (named as a primary, alongside Qwen3.5,
  Granite 4.2, and Ministral 3 — all three of which were executed),
  Qwen2.5, and Llama 3.x (both named as optional controls). Earlier
  shortlist work also considered these three. They were not part of the
  executed first-round six-model batch. The durable record does not
  establish a separate quality-based, licensing-based, availability-
  based, or any other rejection of these three models, so this report
  does not treat their absence as evidence against them.
- **Conditional, and executed:** Gemma 4 was named conditionally on
  independently verifying its weight-file download (not just its model
  card) was ungated. It was executed in this round as
  `Gemma-4-E4B-it-Q4_K_M`. The durable record does not separately log
  that this verification step was performed and passed as its own
  recorded fact; the existence of a working local `.gguf` file and a
  completed benchmark run against it (§8) is practical evidence a usable
  download existed, but this report does not claim the specific
  verification the design record called for was formally carried out
  and recorded.

### Larger and accelerated-tier candidates

No durable source in this repository names a specific larger
accelerated-tier candidate (for example, a particular ~27B-parameter-
class model) for this or any planned round. What is durably documented
is more general: `D-029` establishes a separate accelerated hardware
profile (RTX 3090-class, 24GB VRAM) as a real, distinct evaluation
target, and earlier design work defers "dedicated reasoning-mode
variants" and larger releases in the same families (e.g. Qwen3.8) to a
second round.
This report does not go further than that — it does not assert that any
specific larger model was considered and deferred, only that the general
concepts of a second, larger-capacity evaluation round and a separate
accelerated hardware profile are both durably established design
intent.

### What this round does not claim

The six-candidate round does not claim to:

- cover every strong local model available in 2026;
- prove that any excluded or not-yet-run model is inferior to any
  executed candidate;
- establish a universal ranking of local models; or
- close the shortlist to future reconsideration.

### What would justify adding another candidate later

Consistent with the round being a targeted screening rather than a
final survey, a later round remains open to new candidates where, for
example:

- a current finalist (§12) exposes a capability gap during further
  evaluation;
- a materially stronger local model relevant to this product's needs
  becomes available;
- a different deployment tier (e.g. the accelerated hardware profile,
  `D-029`) calls for a different model class than the CPU-oriented
  baseline this round targeted; or
- the human owner directs that another comparator be added.

## 4. Frozen protocol

Identical across all six candidates — no candidate-specific prompt
tuning, and no model-specific special handling beyond what the frozen
harness/adapter contract already provides:

- Runtime: llama.cpp (`llama-server`, build `10951`, commit
  `093a2f86c`), served over its OpenAI-compatible
  `/v1/chat/completions` endpoint.
- CPU-only inference (`--n-gpu-layers 0`).
- Context size: 8192.
- Reasoning/thinking mode: off (`--reasoning off`).
- Sampling: `temperature=0.0`, `max_tokens=512` — fixed adapter defaults
  (`LlamaCppHttpProvider`), applied uniformly to every candidate, never
  overridden per candidate.
- The same 6 `AI-06` fixture tasks (`context_inference`,
  `guided_questions`, `finding_explanation`, `remediation`,
  `rule_description`, `report_summary`), fixture set version `1`.
- `max_retries=2`, `consistency_repeats=2`.
- The same harness (`ai_benchmark.runner.run_benchmark`), the same
  benchmark-only adapter (`ai_benchmark.adapters.llama_cpp_http.
  LlamaCppHttpProvider`, `WP-044`), the same validator
  (`ai_boundary.validation.validate_model_output`, unmodified, `WP-045`
  numeric-grounding fix applied), and the same fixed JSON-output prompt
  contract.

## 5. Aggregate results

| Candidate | Accepted | Validity rate | Consistency rate | Avg. retries used | Avg. duration (ms) |
|---|---|---|---|---|---|
| Qwen3.5-4B-Q4_K_M | 6/6 | 1.0 | 1.0 | 0.167 | 17,685.49 |
| Qwen3.5-9B-Q4_K_M | 6/6 | 1.0 | 1.0 | 0.167 | 28,704.09 |
| Granite-4.2-8B-Q4_K_M | 5/6 | 0.833 | 0.0 | 0.333 | 22,469.63 |
| Gemma-4-E4B-it-Q4_K_M | 5/6 | 0.833 | 0.0 | 0.5 | 16,254.76 |
| Granite-4.2-3B-Q4_K_M | 3/6 | 0.5 | 0.0 | 0.667 | 12,131.69 |
| Ministral-3-3B-Instruct-Q4_K_M | 0/6 | 0.0 | 0.0 | 0.0 | 12,749.67 |

Full per-candidate machine-readable records are published alongside this
report under `results/` (see "Machine-readable evidence" below).

**Read section 7 ("What `consistency_rate` measures") before interpreting
the Consistency-rate column** — a `0.0` value does not always mean
"measured and found inconsistent."

## 6. Per-fixture outcomes

Legend: **A** = accepted, **R** = rejected (validator), **E** = provider
error (output did not parse as valid JSON, never reached the
validator), retries = retries actually used, consistent = repeat-call
consistency result (see section 7 for what this means).

### Qwen3.5-4B-Q4_K_M (baseline)

| Fixture | Outcome | Rejection reason(s) | Retries | Consistent |
|---|---|---|---|---|
| context_inference | A | — | 0 | true |
| guided_questions | A | — | 0 | true |
| finding_explanation | A | — | 0 | true |
| remediation | A | — | 0 | true |
| rule_description | A | — | 0 | true |
| report_summary | A | — | 1 | true |

### Qwen3.5-9B-Q4_K_M

| Fixture | Outcome | Rejection reason(s) | Retries | Consistent |
|---|---|---|---|---|
| context_inference | A | — | 0 | true |
| guided_questions | A | — | 0 | true |
| finding_explanation | A | — | 0 | true |
| remediation | A | — | 0 | true |
| rule_description | A | — | 0 | true |
| report_summary | A | — | 1 | true |

### Granite-4.2-8B-Q4_K_M

| Fixture | Outcome | Rejection reason(s) | Retries | Consistent |
|---|---|---|---|---|
| context_inference | A | — | 0 | false (measured) |
| guided_questions | A | — | 0 | false (measured) |
| finding_explanation | A | — | 0 | false (measured) |
| remediation | A | — | 0 | false (measured) |
| rule_description | A | — | 0 | false (measured) |
| report_summary | R | unknown_numeric_claim | 2 | false (measured) |

### Gemma-4-E4B-it-Q4_K_M

| Fixture | Outcome | Rejection reason(s) | Retries | Consistent |
|---|---|---|---|---|
| context_inference | A | — | 0 | false (measured) |
| guided_questions | A | — | 0 | false (measured) |
| finding_explanation | A | — | 0 | false (measured) |
| remediation | A | — | 0 | false (measured) |
| rule_description | A | — | 1 | false (measured) |
| report_summary | R | unknown_numeric_claim | 2 | false (measured) |

### Granite-4.2-3B-Q4_K_M

| Fixture | Outcome | Rejection reason(s) | Retries | Consistent |
|---|---|---|---|---|
| context_inference | A | — | 0 | false (measured) |
| guided_questions | E | — (malformed JSON, see §8) | 0 | false (not evaluated) |
| finding_explanation | R | unknown_numeric_claim | 2 | false (measured) |
| remediation | A | — | 0 | false (measured) |
| rule_description | A | — | 0 | false (measured) |
| report_summary | R + E | unknown_numeric_claim, then malformed JSON on the final attempt (see §8) | 2 | false (not evaluated) |

### Ministral-3-3B-Instruct-Q4_K_M

| Fixture | Outcome | Rejection reason(s) | Retries | Consistent |
|---|---|---|---|---|
| context_inference | E | — (malformed JSON, see §8) | 0 | false (not evaluated) |
| guided_questions | E | — (malformed JSON, see §8) | 0 | false (not evaluated) |
| finding_explanation | E | — (malformed JSON, see §8) | 0 | false (not evaluated) |
| remediation | E | — (malformed JSON, see §8) | 0 | false (not evaluated) |
| rule_description | E | — (malformed JSON, see §8) | 0 | false (not evaluated) |
| report_summary | E | — (malformed JSON, see §8) | 0 | false (not evaluated) |

## 7. What `consistency_rate` measures

This is a precise, source-verified description of the harness's own
consistency metric (`ai_benchmark/runner.py`), not a general claim about
model reliability:

- After a fixture's accept/retry loop finishes, the harness checks
  consistency **only if the final attempt in that loop returned a
  JSON-parseable response** — regardless of whether the validator
  ultimately accepted or rejected it. If the final attempt instead
  produced a non-JSON-parseable output (a provider error), consistency
  is **never evaluated** for that fixture and defaults to "not
  consistent."
- When evaluated, the harness re-sends the fixture's **original,
  unmodified prompt** (not any retry-corrected version) up to 2
  additional times and compares each repeat's parsed JSON output to the
  very first attempt's parsed JSON output using **exact structural
  equality**. A single mismatch (or a repeat call itself failing) marks
  the fixture "not consistent."
- **This is a strict exact-match-after-JSON-parsing repeatability
  check — the model's raw text output is parsed into a JSON object and
  compared to the first attempt's parsed JSON object using Python dict
  equality — under fixed decoding parameters (`temperature=0.0`,
  `max_tokens=512` — the same for every candidate). It is not a
  raw-output byte-comparison, and not a semantic-similarity,
  paraphrase-tolerant, or general model-stability judgment.** A repeat
  response that says the same thing in different words counts as
  "inconsistent" under this metric, unless it happens to parse to an
  identical JSON object. The metric also does not identify *why* two
  attempts differed.

Applying this to the data above:

- **Qwen3.5-4B and Qwen3.5-9B**: consistency was genuinely evaluated for
  all 6 fixtures each, and every repeat's parsed JSON output was exactly
  equal to the first attempt's parsed JSON output under the benchmark's
  Python-dict equality check — a real, measured result of full
  exact-match consistency under this protocol.
- **Granite-4.2-8B, Gemma-4-E4B-it, and 4 of Granite-4.2-3B's 6
  fixtures**: consistency was genuinely evaluated (the final attempt did
  parse as JSON) and found **not** exact-match consistent, despite
  `temperature=0.0` — a real, measured non-determinism signal. The
  harness does not isolate the cause (e.g. multi-threaded CPU
  floating-point summation order is a known source of non-deterministic
  numerical results in llama.cpp even at zero temperature, which could
  in turn change the parsed JSON content, but this benchmark cannot
  confirm that as the specific cause here).
- **Ministral-3-3B-Instruct (all 6 fixtures) and 2 of Granite-4.2-3B's 6
  fixtures (`guided_questions`, `report_summary`)**: consistency was
  **never evaluated** — the final attempt's output did not parse as
  JSON, so the harness never reached the repeat-comparison step. Their
  `consistency_rate` contribution of `0.0` reflects "not measurable,"
  not "measured and found unstable."

**No sentence in this document should be read as a claim about any
candidate's semantic reliability, reasoning stability, or general
trustworthiness beyond exactly what is described above.**

## 8. Model-quality / contract-behavior findings

- **Ministral-3-3B-Instruct — 0/6.** Every fixture's response was
  wrapped in a ` ```json ... ``` ` markdown code fence rather than the
  bare JSON object the fixed prompt contract requires, causing the
  adapter's JSON parser to fail on every attempt. The narrative content
  visible inside those fences was substantively reasonable; the failure
  is a formatting-contract miss, not necessarily a reasoning-quality
  one (see §9 for a related harness-observation caveat).
- **Granite-4.2-3B — 3/6.** `guided_questions` leaked a literal `<think>`
  block into its output despite `--reasoning off`, and both
  `guided_questions` and `report_summary` were truncated mid-string
  (plausibly related to the fixed `max_tokens=512` ceiling — see §9).
  `finding_explanation` and `report_summary` were also rejected for
  `unknown_numeric_claim` on the JSON-parseable attempts that did occur.
- **Granite-4.2-8B and Gemma-4-E4B-it — 5/6 each.** Both failed only on
  `report_summary`, both via `unknown_numeric_claim` after exhausting
  retries — the aggregate/report-level fixture appears to be the
  hardest numeric-grounding case for both mid-size candidates in this
  round.
- **Qwen3.5-4B and Qwen3.5-9B — 6/6 each,** with genuinely measured,
  fully exact-match-repeatable output across all 6 fixtures (see §7).

## 9. Harness / validator observations

- **Retry-policy asymmetry.** Validator-level rejections (e.g.
  `unknown_numeric_claim`) consumed configured retries with
  `retry_feedback` sent back to the model (Granite-4.2-3B, Granite-4.2-8B,
  and Gemma-4-E4B-it's `report_summary` cases all show
  `retries_used: 2`). Provider-level JSON parse failures did **not**
  consume any retry in this round (Ministral's 6 failures all show
  `retries_used: 0`) — the harness's retry loop only re-prompts after a
  *validator* rejection, not after a raw parse failure. This is existing
  `WP-043` harness behavior, unmodified by this report; whether parse
  failures should also receive a corrective retry pass is an open
  question for future harness work, not decided here.
- **Fixed `max_tokens=512`.** This is a frozen adapter default applied
  identically to every candidate (§4), not a per-candidate choice. It is
  a plausible contributor to the truncated/malformed output observed for
  more verbose candidates (Granite-4.2-3B in particular) — disclosed as
  a protocol characteristic, not attributed solely to model quality.
- **Sequential mixed outcomes are possible within one fixture's retry
  loop.** Granite-4.2-3B's `report_summary` shows both a validator
  rejection reason (`unknown_numeric_claim`, from an earlier
  JSON-parseable attempt) and a provider error (from the final attempt
  after retries were exhausted) recorded together — the harness records
  the last validator outcome reached and the final attempt's transport
  outcome independently; these are not contradictory, but readers should
  not assume "has a rejection reason" implies "the final attempt
  parsed."

## 10. EDS / host-service tooling observations

*(Infrastructure only — none of the following affected any model result
above; every affected service start was independently re-verified
healthy and serving the correct candidate, via the same governed
health/identity checks, before its benchmark ran.)*

- The governed activity runner's service-replacement wait window was
  shorter than actual model load time for two larger candidates
  (Qwen3.5-9B, Granite-4.2-8B), surfacing as a client-side timeout even
  though the server started correctly. Re-verified via an independent
  health/identity check before proceeding.
- One service-replacement call encountered a transient tooling error
  (a momentarily-absent internal heartbeat file) that resolved on retry,
  with the underlying host-resident process confirmed continuously
  alive throughout.

## 11. Explicit limitations of this screening round

- **Single dataset.** All fixtures are grounded in one dataset
  (`demo-data/sales_demo.csv`), per `docs/decision-log.md` D-032's own
  disclosed "small and reproducible first round" scope. A selection
  based only on this round risks fitting that dataset's own quirks.
- **Single hardware/runtime configuration.** CPU-only, one machine
  class, llama.cpp only — no Ollama comparison yet (the second named
  runtime finalist, D-007/D-030), no accelerated-hardware-tier data, and
  no resource observations (peak RSS/VRAM) were captured this round.
- **No narrative-quality, semantic-correctness-beyond-grounding, or
  category-accuracy scoring.** Per D-032's own confirmed scoring
  boundary, the harness measures structural validity/groundedness,
  latency, retry rate, and repeat-call consistency only.
- **No numeric acceptance threshold exists anywhere in this project's
  decisions** for any of these metrics — nothing here should be read as
  passing or failing an as-yet-undefined bar.
- **`consistency_repeats=2` is a small sample** for any consistency-rate
  claim, and (per §7) is not evaluated at all for several fixtures in
  this round.
- **Formatting-contract failures are not yet distinguished from
  reasoning failures** in the harness's own scoring — Ministral's 0/6 in
  particular may be recoverable with a prompt or parser adjustment not
  attempted in this round (see §9).

## 12. Evidence-based narrowing (not a decision)

Based on the data above, **Qwen3.5-4B-Q4_K_M and Qwen3.5-9B-Q4_K_M are
finalists for the next evaluation round** — both reached 6/6 accepted
with genuinely measured, fully exact-match-repeatable output, the only
two candidates in this screening to do so.

**This is a narrowing for further evaluation, not a model selection, a
runtime selection, a quantization decision, a ranking of all six
candidates, or a closure of the "hands-on AI-06 evaluation" phase.** No
other candidate is disqualified from future re-testing, particularly
where §9/§11 identify a plausible non-model-quality contributor (fixed
`max_tokens`, markdown-fence formatting, single-dataset scope) to a
candidate's result.

## 13. Evidence still required before the human decision gate

At minimum, before the runtime/model/quantization/per-hardware-tier
decision named in `docs/decision-log.md` D-032/D-033 can be made:

- A second, distinct dataset, to corroborate any narrowing that treats
  this round's results as more than dataset-specific.
- A runtime comparison against Ollama, the still-open second finalist
  runtime (D-007/D-030) — this round tested llama.cpp only.
- Resource observations (peak RSS/VRAM) per candidate, which this round
  did not measure, needed to evaluate per-hardware-tier fit.
- A decision on whether Ministral-3-3B-Instruct's and Granite-4.2-3B's
  parse-failure modes are recoverable with a harness/prompt-level
  adjustment (e.g. explicit code-fence stripping, a higher `max_tokens`)
  before treating their low scores as a final model-quality verdict.
- Any additional rounds the human owner directs, consistent with
  `docs/decision-log.md` D-032's own "not yet decided" list (exact
  model, quantization, per-tier default all remain open).

## Provenance

This report and the accompanying machine-readable artifacts under
`results/` are sourced directly from two governed, non-work-package EDS
evaluation activities, phase `hands-on AI-06 evaluation`:

- **`AI-06-hands-on-full-set-20260915`** (2026-09-15) — the
  Qwen3.5-4B-Q4_K_M baseline, digest
  `6882a9f2708f7b42c9b7dfcb7de4fa85ea70ed7581eb3cd990a47bd612add8c4`.
- **`AI-06-multi-candidate-batch-20260916`** (2026-09-16) — the
  remaining 5 candidates, digest
  `5547f49a18309e9e1e8f6e040156b423cac751da8be801755000c73329e4ec7f`.

Both activities ran under governed EDS activity authority
(`work_type` non-WP evaluation; `roadmap_advancement: false`;
`return_phase: "hands-on AI-06 evaluation"`), using the merged
`AI-06`/`WP-043` benchmark harness and `WP-044`'s benchmark-only
`LlamaCppHttpProvider` adapter, with `WP-045`'s numeric-grounding fix
already applied. Every candidate's served-model identity was
independently verified against the intended candidate (via the running
server's own reported model metadata) before its benchmark ran.

## Machine-readable evidence

One sanitized `BenchmarkReport` JSON document per candidate is published
under `results/` alongside this report, using the harness's own existing
result schema (`schema_version: "2"`) unmodified. The only sanitization
applied: each of the 5 newer candidates' free-text `notes`/
`config.notes` fields had the locally-served model's filesystem path
replaced with a fixed redaction statement — every other field (aggregate
metrics, per-fixture results, retries, consistency, duration, provider
errors, rejection reasons) is preserved exactly as recorded by the
harness.

- `results/qwen3.5-4b-q4_k_m.json`
- `results/qwen3.5-9b-q4_k_m.json`
- `results/granite-4.2-3b-q4_k_m.json`
- `results/granite-4.2-8b-q4_k_m.json`
- `results/ministral-3-3b-instruct-q4_k_m.json`
- `results/gemma-4-e4b-it-q4_k_m.json`
