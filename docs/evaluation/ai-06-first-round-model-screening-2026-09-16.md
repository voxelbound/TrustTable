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

## 10. Host-service tooling observations

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
- During the later controlled performance/resource comparison (§14), a
  candidate-switch step once reported success while the previous
  candidate's process was still transiently reachable; this was caught
  by the same independent identity re-verification convention before
  any measurement was captured, and one governed service-management
  step needed a manual restart to fully clear it. No measurement in §14
  reflects the wrong candidate.

## 11. Explicit limitations of this screening round

- **Single dataset.** All fixtures are grounded in one dataset
  (`demo-data/sales_demo.csv`), per `docs/decision-log.md` D-032's own
  disclosed "small and reproducible first round" scope. A selection
  based only on this round risks fitting that dataset's own quirks.
- **Single hardware/runtime configuration.** CPU-only, one machine
  class, llama.cpp only — no Ollama comparison (the second named
  runtime finalist, D-007/D-030) and no accelerated-hardware-tier data
  exist anywhere in this evaluation. Peak working-set memory was
  captured for the two finalists only, in the later controlled
  comparison (§14) — not for all six first-round candidates, and not on
  the accelerated hardware tier.
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

This narrowing was followed by a further blind qualitative comparison
(§13) and a controlled performance/resource comparison (§14) between
the two finalists, leading to a bounded model decision (§15).

## 13. Blind qualitative comparison: Qwen3.5-4B vs Qwen3.5-9B

Following §12's narrowing, a dedicated blind evaluation round compared
the two finalists' actual generated output (not just structural
acceptance) on the same six fixtures. Each fixture's two outputs were
anonymized as "Candidate A"/"Candidate B" (independently randomized per
fixture, mapping withheld) and reviewed qualitatively before any reveal.

**Validity/consistency reconfirmed:** both candidates again reached
6/6 accepted, with identical retry behavior to the first round (exactly
one retry, on `report_summary` only, both candidates).

**De-blinded per-fixture result:**

| Fixture | Result |
|---|---|
| `context_inference` | Qwen3.5-4B better |
| `guided_questions` | Qwen3.5-4B slightly better |
| `report_summary` | Qwen3.5-4B slightly better |
| `finding_explanation` | Equivalent |
| `remediation` | Qwen3.5-9B better |
| `rule_description` | Qwen3.5-9B better |

Qwen3.5-4B wins 3 fixtures (1 clearly, 2 slightly), Qwen3.5-9B wins 2
(both clearly), 1 is equivalent. **This is a close, mixed result — it
does not establish a consistent output-quality advantage for either
candidate.**

## 14. Controlled performance/resource comparison: Qwen3.5-4B vs Qwen3.5-9B

A separate evaluation measured latency and peak memory under
controlled conditions — the host machine was confirmed idle and
reserved for the full duration before measurement began, and the same
frozen protocol (§4) and six fixtures were used with no qualitative
review. Two runs per candidate were captured, alternating candidate
order to reduce warmup/order bias.

**This is the only latency/resource evidence in this report that
should be treated as decision-grade.** An earlier, uncontrolled
measurement pass (superseded, not otherwise published here) produced
inconsistent latency figures across runs, later attributed to
background host load rather than genuine model behavior — a
methodology lesson, not a model finding.

**Aggregate latency (sum of all 6 fixtures per run, model already
loaded), range across the 2 runs per candidate:**

| Candidate | Range | Notes |
|---|---|---|
| Qwen3.5-4B | 125.6 s – 126.0 s | Tight, ~0.3% run-to-run spread |
| Qwen3.5-9B | 166.5 s – 188.8 s | Wide, ~13% run-to-run spread |

Qwen3.5-9B is roughly 30–50% slower in aggregate than Qwen3.5-4B under
these conditions (a rough indicator from a 2-run range, not a precise
point estimate).

**Per-fixture latency ranges (ms), across the 2 runs per candidate:**

| Fixture | Qwen3.5-4B | Qwen3.5-9B | Observation |
|---|---|---|---|
| `context_inference` | 13,917 – 13,954 | 27,042 – 30,558 | 9B consistently ~2x slower |
| `guided_questions` | 13,819 – 13,931 | 12,750 – 15,978 | Overlapping — 9B's faster run beat both 4B runs |
| `finding_explanation` | 14,390 – 14,545 | 19,132 – 22,575 | 9B consistently ~40–55% slower |
| `remediation` | 17,514 – 17,703 | 30,698 – 34,402 | 9B consistently ~75–95% slower |
| `rule_description` | 17,621 – 17,725 | 16,926 – 20,513 | Overlapping — 9B's faster run beat both 4B runs |
| `report_summary` (incl. 1 retry) | 48,223 – 48,260 | 59,942 – 64,795 | 9B consistently ~24–34% slower |

Stated plainly: on 4 of 6 fixtures Qwen3.5-9B is consistently and
substantially slower even under controlled conditions; on the other 2,
the two candidates' ranges overlap. Qwen3.5-9B also shows a
substantially wider run-to-run latency spread than Qwen3.5-4B on this
same reserved host.

**Peak working-set memory, range across the 2 runs per candidate:**

| Candidate | Range | Approx. |
|---|---|---|
| Qwen3.5-4B | 4,607,537,152 – 4,607,590,400 bytes | ~4.29 GiB, essentially identical across runs |
| Qwen3.5-9B | 7,069,544,448 – 7,305,318,400 bytes | ~6.58–6.80 GiB |

Qwen3.5-9B's peak working set is roughly 50–60% larger than
Qwen3.5-4B's.

**Sample-size caveat:** 2 runs per candidate is enough to see rough
magnitude and to observe that Qwen3.5-4B's own run-to-run behavior is
markedly tighter than Qwen3.5-9B's — it is not enough for tight
statistical precision on the exact cost difference.

## 15. Bounded model decision

**Qwen3.5-4B-Q4_K_M is selected as the CPU-oriented/default TrustTable
model.** Qwen3.5-9B-Q4_K_M is retained, not disqualified, as a
documented higher-capacity reevaluation/escalation candidate, to be
revisited only if a future, product-realistic workload demonstrates a
concrete capability limit in Qwen3.5-4B that Qwen3.5-9B is shown to
resolve. Full decision record: `docs/decision-log.md` D-034.

**Basis:** structural reliability does not distinguish the two
candidates (§13); the blind qualitative comparison was close and mixed
(§13); the controlled performance/resource comparison shows Qwen3.5-9B
costs materially more — roughly 30–50% higher aggregate latency and
roughly 50–60% higher peak memory (§14) — without a demonstrated
product-relevant capability advantage to justify that cost as the
default.

**This is a bounded product decision for the evaluated candidates and
the baseline hardware profile — not a claim that Qwen3.5-4B is
universally better than Qwen3.5-9B, and not a decision about runtime or
the accelerated hardware profile.** See §16.

## 16. Evidence still required before the human decision gate

The human decision gate named in `docs/decision-log.md` D-032/D-033
covers four items: runtime, model family/exact model, quantization, and
per-hardware-tier default. **§15's decision resolves the model
family/exact model and baseline-hardware-tier-default items.** Q4_K_M
is recorded as the selected quantization because it is what the
selected model was evaluated at throughout this investigation — no
comparative quantization study was performed, and this should not be
read as Q4_K_M having been shown superior to any alternative. What
remains open:

- **Runtime.** No round in this evaluation compared Ollama at all —
  every round used a benchmark-only `llama.cpp` adapter exclusively
  (disclosed throughout as evaluation tooling, not the production
  provider integration). This must still be decided before the real
  local-inference provider work can start.
- **Accelerated/developer hardware-tier default.** Every round ran
  under the frozen protocol's CPU-only configuration; the
  GPU-accelerated hardware profile (`docs/decision-log.md` D-029's
  second named profile) was never evaluated. Whether Qwen3.5-9B, a
  different model, or the same baseline default should apply on that
  profile is unaddressed.
- A second, distinct dataset would still corroborate the underlying
  first-round screening (§11) if that screening's own narrowing is ever
  revisited, but is not required for the model decision already made in
  §15.
- A decision on whether Ministral-3-3B-Instruct's and Granite-4.2-3B's
  parse-failure modes (from the first-round screening) are recoverable
  with a harness/prompt-level adjustment remains open but is not a
  blocker to this decision, since neither candidate was a finalist.

**Per the human owner's explicit instruction, the model benchmark
itself (first-round screening, blind qualitative comparison, and
controlled performance comparison) is not to be re-run unless a
genuinely new product requirement creates new evidence needs.**

## Provenance

This report and the accompanying machine-readable artifacts under
`results/` are sourced from four evaluation rounds:

- **First-round screening** (2026-09-15, then 2026-09-16): the
  Qwen3.5-4B-Q4_K_M baseline candidate, followed by the remaining five
  candidates.
- **Blind qualitative comparison** (2026-09-16): Qwen3.5-4B vs
  Qwen3.5-9B, the two finalists (§13).
- **Controlled performance/resource comparison** (2026-09-16):
  Qwen3.5-4B vs Qwen3.5-9B, with the host machine confirmed idle and
  reserved for its full duration before measurement began (§14).

All four rounds used the same benchmark harness (§4) and its
`llama.cpp`-only real-runtime adapter — evaluation tooling, not the
production AI provider integration. Every candidate's served-model
identity was independently verified against the intended candidate
(via the running server's own reported model metadata) before its
benchmark ran, in every round.

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
