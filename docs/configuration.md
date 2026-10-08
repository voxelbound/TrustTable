# Configuration

Repository-foundation stage (`FND-02`): this document describes every
setting the backend's typed configuration system (`Settings`,
`backend/src/trusttable_backend/config.py`) validates today. `Settings`'
own built-in defaults are the runtime source of truth; `.env.example`
documents those same defaults for humans and is not read by the
application itself.

Most settings listed here are **validated but not yet consumed** — they
exist because later backlog items (`DB-01` persistence, `JOB-01`
background workers, `AI-01`/`AI-03` LLM providers, ingestion/parsing
limits) will read them once that code exists. `FND-02` guarantees they
are present, correctly typed, and bounded from day one.

## How configuration is loaded

- Every variable below is read from the process environment (case-
  insensitive). Unrecognized environment variables are ignored.
- An optional `.env` file at the repository root is read first, if
  present, purely as a native-development convenience — copy
  `.env.example` to `.env` and edit it. Its absence is not an error.
- `docker-compose.yml` does not require a `.env` file either: with none
  present, the backend container starts on `Settings`' own defaults. If
  a repository-root `.env` does exist, Compose passes it through.
- **Invalid configuration stops the process at startup** (a Pydantic
  validation error, non-zero exit), both natively and in Docker. The
  application never runs with unvalidated or partially-invalid
  configuration.
- No setting value is ever logged or serialized as a complete object.
  `DATABASE_URL` and `LLM_BASE_URL` are treated as potentially sensitive
  (a future non-SQLite/non-local value could embed credentials) and are
  excluded from the configuration object's default representation.

## Application

| Variable | Type | Default | Effect |
|---|---|---|---|
| `APP_ENV` | enum: `development` \| `test` \| `production` | `development` | Reported as `environment_mode` in `GET /api/v1/version`; later code may vary behavior by environment. |
| `LOG_LEVEL` | enum: `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` | `INFO` | Will configure the application's logging verbosity once structured logging exists (`FND-04`). Not yet consumed. |
| `DATABASE_URL` | non-empty string (potentially sensitive) | `sqlite:////data/trusttable.db` | Will configure SQLAlchemy's database connection once persistence exists (`DB-01`). Not yet consumed. |
| `DATA_DIRECTORY` | non-empty string | `/data` | Will configure where uploaded files and derived artifacts are stored once that code exists. Not yet consumed. |

## Local limits

| Variable | Type | Default | Effect |
|---|---|---|---|
| `MAX_FILE_SIZE_MB` | positive integer | `100` | Maximum accepted compressed upload size for `.csv` and `.xlsx` files. A larger upload is refused with `413 FILE_TOO_LARGE`. |
| `MAX_ROWS` | positive integer | `1000000` | Maximum data rows in a CSV file or in the chosen worksheet. A file over the limit ends as a `failed` analysis. |
| `MAX_COLUMNS` | positive integer | `500` | Maximum columns in a CSV file or in the chosen worksheet. A file over the limit ends as a `failed` analysis. |
| `MAX_WORKSHEETS` | positive integer | `20` | Maximum worksheets in an uploaded workbook. A workbook with more is refused at upload with `413 WORKBOOK_EXPANSION_LIMIT`. |
| `MAX_UNCOMPRESSED_WORKBOOK_MB` | positive integer | `500` | Maximum uncompressed workbook size (expansion-bomb defense). A workbook that declares or unpacks to more is refused at upload with `413 WORKBOOK_EXPANSION_LIMIT`. |
| `MAX_CELL_COUNT` | positive integer | `50000000` | Maximum cells in the chosen worksheet. A worksheet over the limit ends as a `failed` analysis (`CELL_LIMIT_EXCEEDED`); the CSV parser has no cell-count limit beyond its row and column limits. |
| `ANALYSIS_RETENTION_HOURS` | non-negative integer (`0` = unlimited) | `0` | Will control automatic analysis retention once persistence exists (`DB-01`). |
| `BACKGROUND_WORKER_COUNT` | positive integer | `2` | Will size the bounded in-process worker pool once background jobs exist (`JOB-01`). |
| `STAGING_MAX_COUNT` | positive integer | `5` | Maximum files held in temporary staging at once (`UX-02`, `docs/api-specification.md` §7). A further file is refused with `409 STAGING_FULL`. |
| `STAGING_MAX_TOTAL_MB` | positive integer | `250` | Maximum total size of all staged files. A file that would exceed it is refused with `409 STAGING_FULL`. A single file is still bounded by `MAX_FILE_SIZE_MB`. |
| `STAGING_TTL_MINUTES` | positive integer | `60` | How long a staged file is kept before it is deleted. The expiry is fixed when the file is staged. |

The three `STAGING_*` limits are installation-controlled resource limits. They are not
product-managed settings and the product never edits them.

These limits are read from the settings on every parse of a stored file, not
only at upload: the analysis run, a retry, and every later step that reads
the file again (row context, rules, reports, explanations) use the same
values. Lowering a limit therefore also applies to analyses created earlier;
if a stored file no longer fits, the steps that read it again fail for that
analysis. Leaving a variable unset keeps the default shown above.

## LLM provider

> **Note (2026-09-16, `AI-03` implemented):** the local AI runtime
> decision named below is now resolved — `llama.cpp` is the selected
> v0.2 baseline runtime (`docs/decision-log.md` D-035), and
> Qwen3.5-4B-Q4_K_M is the selected baseline-profile model (`D-034`).
> `LLM_PROVIDER`'s `ollama` literal (the placeholder this note
> previously described) has been replaced with `llama_cpp`, the real
> value `AI-03`'s provider is registered under. The accelerated/GPU
> hardware-tier default remains a separate, later, explicitly deferred
> decision (`D-035`) and does not affect these defaults.

| Variable | Type | Default | Effect |
|---|---|---|---|
| `LLM_PROVIDER` | enum: `disabled` \| `mock` \| `llama_cpp` | `disabled` | Selects the active AI provider (`AI-01`/`AI-02`/`AI-03`). `llama_cpp` requires `LLM_BASE_URL`/`LLM_MODEL` to point at a running `llama-server` instance. |
| `LLM_BASE_URL` | non-empty string (potentially sensitive) | `http://host.docker.internal:8081` | The `llama-server` (`llama.cpp`) endpoint `AI-03`'s provider connects to when `LLM_PROVIDER=llama_cpp`. `8081` is a dedicated port distinct from TrustTable's own frontend port (`8080`); `llama-server` is run with `--no-webui` in the documented/supported runtime profile (`docs/decision-log.md` D-036, `docs/local-development.md`). |
| `LLM_MODEL` | string (unconstrained, default empty) | `""` (empty) | The model identifier `AI-03`'s provider sends as the request's `model` field — set it to a model **name** such as the baseline-profile model `Qwen3.5-4B-Q4_K_M` (`D-034`). It may also be a file path or repository id; that works, but the backend never returns it to a client: API responses and the UI show only a sanitized last path segment plus a derived label such as "Local AI · llama.cpp · Qwen3.5 4B" (`AI-08`, `docs/decision-log.md` D-040). A `llama-server` serves the single model it was started with and does not require this to match. |
| `LLM_TEMPERATURE` | float, `0`–`2` | `0` | Validated at startup. **Not yet applied:** the API routes construct the provider with its own default temperature (`0.0`); wiring this setting through is not part of `AI-08`. |
| `LLM_CONTEXT_WINDOW` | positive integer | `8192` | Validated at startup. **Not applied by TrustTable:** the context window is a `llama-server` start-up flag (`--ctx-size`, `docs/installation-linux.md`). |
| `LLM_TIMEOUT_SECONDS` | positive integer | `120` | The timeout of one model call. The structured finding analysis (`AI-08`) asks for a longer answer than earlier calls; on a CPU-only machine raise this (for example `300`) if Finding Detail reports that an AI attempt could not complete. |
| `LLM_SEND_SAMPLE_VALUES` | boolean | `false` | Will gate whether sample dataset values may ever be sent to a model. No route reads it today: no request sends dataset samples (`docs/decision-log.md` D-040). Off by default. |
| `LLM_MAX_SAMPLE_VALUES` | non-negative integer | `10` | Would bound how many sample values may be sent if `LLM_SEND_SAMPLE_VALUES` were enabled; unused while no request sends samples. |

## Security

| Variable | Type | Default | Effect |
|---|---|---|---|
| `PROMPT_INJECTION_DETECTION_ENABLED` | boolean | `true` | Will gate the prompt-injection detector once it exists (`DET-SEC-01`). |
| `MAX_TEXT_VALUE_LENGTH_FOR_ANALYSIS` | positive integer | `10000` | Longest cell value kept when a file is parsed; a longer value is truncated and the dataset records a parsing warning. |
| `MAX_COLUMN_NAME_LENGTH` | positive integer | `256` | Longest column name kept when a file is parsed; a longer name is truncated and the dataset records a parsing warning. |

## Operational visibility

`GET /api/v1/health/ready` includes a `configuration` check confirming
`Settings` loaded successfully. Because invalid configuration already
prevents the process from starting (see above), this check can only be
observed as `"ok"` once the application is serving requests — it exists
as a real, extensible check for future in-process reconfiguration paths,
not a constant.

## Planned: product-managed settings and deployment overrides (planned, not built)

> Nothing in this section exists today. Every setting above is read from the
> environment and cached for the life of the process. This section records the
> owner-confirmed target (`docs/decision-log.md` D-066) and two facts a reader needs.

- **Precedence.** For the small allowlist of user-manageable product settings (for
  example whether AI assistance is enabled and the active supported AI profile), the
  effective value will be: an explicit deployment override, then a stored user setting,
  then the built-in default. An *explicit deployment override* is a value an operator
  configured. It is not a default that packaging or a container supplies, and it is never
  detected by comparing a value with the default.
- **Managed by the installation.** A setting that has an explicit override is shown
  read-only with its effective value and a plain explanation. The product never edits
  `.env` or deployment configuration. *Reset to default* removes the stored value.
- **What stays here.** Deployment configuration (database, data directory, log level,
  worker count) and the security and resource limits stay installation-controlled and are
  never overridable by a stored value. Display preferences stay in the browser.
- **`.env.example`.** The settings slice will comment out UI-managed settings in
  `.env.example` instead of setting them to their defaults (copying a file that sets every
  value would otherwise look like an explicit override), will test that packaging sets none
  of them, and will explain in plain language which explicit settings prevent in-product
  management for installations that copied the old file. This documentation change does
  not alter `.env.example`, which the existing documentation tests pin to the real defaults.
- **Known defects, tracked and not decisions.** `PROMPT_INJECTION_DETECTION_ENABLED` is
  documented above as the gate of the prompt-injection detector but no code consumes it,
  and `ANALYSIS_RETENTION_HOURS` is likewise consumed by nothing; neither may be offered to
  users as a control until it controls what it claims to. No auto-delete setting is part of
  the redesign: retention is destructive behavior that needs its own design.
- **Advanced exception.** A settings-only response may expose the effective runtime and
  model configuration needed to administer an installation. Raw paths, URLs and other
  technical configuration stay out of analysis, finding, report and other shareable
  responses.
