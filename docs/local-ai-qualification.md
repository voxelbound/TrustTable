# Local AI qualification

TrustTable's AI features are optional and run against a local model. This page
describes the **qualification harness**: a repeatable way to measure how a
particular local model behaves on the path the product actually uses, so that a
model, a timeout and a hardware tier can be chosen from evidence rather than
assumption. The decision it supports is recorded in
[`decision-log.md`](decision-log.md) (D-043).

The harness measures. It does not choose a model, set a threshold or change any
default.

## What it measures

For each finding, TrustTable asks the model for one structured analysis
(explanation, possible business impact, remediation, proposed validation rule)
and validates it. If the answer is accepted, the analysis is shown; otherwise
the built-in guidance is shown instead. The harness runs exactly that path, with
the product's own retry limit, and records which of four things happened:

| Outcome | What the user sees | Product `ai_call_status` |
|---|---|---|
| `accepted_first_attempt` | the AI analysis | `attempted_accepted` |
| `accepted_after_retry` | the AI analysis (after one or two corrections) | `attempted_accepted` |
| `fell_back_rejected` | built-in guidance: every attempt was rejected by the validator | `attempted_rejected` |
| `fell_back_provider_error` | built-in guidance: the provider timed out, was unreachable or returned something unusable | `attempted_provider_error` |

From those it reports:

- **fill rate**: the share of findings for which the AI analysis was shown, and
  the share shown on the first attempt; **fallback rate** is the remainder;
- **latency**: how long a user waits per finding (all attempts together) and per
  attempt, measured by the harness's own clock. Percentiles use the
  nearest-rank rule, so with a small number of findings the 95th percentile is
  simply the slowest;
- **slowest completed attempt**: the slowest attempt that did not fail. A timed
  out attempt lasts about the configured timeout, so this is the figure a
  `LLM_TIMEOUT_SECONDS` choice has to clear;
- counts of rejection reasons and provider error classes.

Everything is reported overall and for each of two conditions: **evidence only**
(the context has not been finalized, so the request carries the finding's
evidence and nothing else) and **confirmed context** (the context has been
finalized, so the request also carries the fields the user confirmed or
corrected, and only those).

## Running it

The harness reads the same `LLM_*` settings as the application (environment
variables and an optional repository-root `.env`; see
[`configuration.md`](configuration.md)) and builds the provider the way the
application does. Start your model server first (see
[`installation-linux.md`](installation-linux.md) and
[`local-development.md`](local-development.md)), then from the `backend/`
directory:

```bash
uv run python -m trusttable_backend.ai_benchmark.qualification_cli \
    --output qualification-run.json \
    --quantization Q4_K_M \
    --hardware-profile baseline
```

`LLM_PROVIDER` must not be `disabled`. Set `LLM_TIMEOUT_SECONDS` to the value you
want to evaluate; it is recorded in the result.

| Option | Meaning |
|---|---|
| `--output PATH` | Required. Where to write the result. The directory must already exist. |
| `--scope per_detector\|all_findings` | One finding per detector that fired (default, 13 cases per condition) or every finding. |
| `--conditions ...` | Which conditions to run (default: both). |
| `--runtime-identifier` | Recorded label for the runtime. Default `llama.cpp`. |
| `--quantization` | Recorded label, for example `Q4_K_M`. |
| `--hardware-profile` | Recorded label. Default `baseline`. |
| `--peak-rss-mb`, `--peak-vram-mb` | Optional resource figures you observed yourself; recorded, never measured by the harness. |
| `--notes` | Free text recorded with the result. Do not put paths or secrets in it. |

Each finding costs between one and three model calls, and the default run
analyses 26 (13 findings under two conditions), so on CPU-only hardware a run can
take a long time. Timings are only meaningful on an otherwise idle machine. Progress is printed
to standard error as `[n/total] case-id condition -> outcome (seconds)`, and a
summary of aggregate figures to standard output. Model output, exception text,
the server address and dataset values are never printed.

The run is deliberately not part of continuous integration: CI never executes a
live model. The automated tests exercise the harness against stubbed providers
and prove it agrees with the real HTTP route.

## Reading a result

The result is one JSON document with sorted keys, so two runs can be compared
with ordinary tools. Its top level carries the schema and case-set versions, the
candidate identity you supplied (runtime, model file name, quantization,
hardware profile), optional resource observations, the configuration the run
used (the product's retry limit and your timeout), every case result with its
attempts, and the aggregates. Fields that were not observed are `null`, never
zero.

A result never contains model output, exception message text, dataset values, the
server URL or an absolute path: a model identifier such as
`/models/Qwen3.5-4B-Q4_K_M.gguf` is reduced to `Qwen3.5-4B-Q4_K_M.gguf`.

## The cases

The cases come from a fixed reference analysis of the bundled demo dataset, so
they are the same on every machine and can be compared across models:

- the first finding of each detector that fired (`--scope all_findings` uses
  every finding);
- for the confirmed-context condition, the reference context is confirmed and
  finalized through the same steps a user follows. Fields the deterministic
  analysis could infer are confirmed as inferred; the fields it could not are
  answered with fixed, documented answers. Inferred fields that a user did not
  confirm are never sent.

The case set is versioned (`case_set_version` in the result). Results with
different versions are not comparable.

## What it does not do

- It does not decide what is good enough. There is no pass mark, and none is
  implied by a result. Interpreting the numbers, and choosing a model, a
  quantization or a timeout, is a human decision.
- It does not score how useful or well written an analysis is; only whether it
  was accepted, how many attempts it took and how long it took.
- It does not apply `LLM_TEMPERATURE`. The application does not pass that setting
  to the provider either, so a measured run describes what the application
  does. Making the setting take effect is a separate change.
- It does not measure memory or GPU use; supply those yourself if you have them.
