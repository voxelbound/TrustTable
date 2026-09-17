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
| `MAX_FILE_SIZE_MB` | positive integer | `100` | Maximum accepted compressed upload size, once upload handling exists. |
| `MAX_ROWS` | positive integer | `1000000` | Maximum accepted dataset row count, once parsing exists. |
| `MAX_COLUMNS` | positive integer | `500` | Maximum accepted column count, once parsing exists. |
| `MAX_WORKSHEETS` | positive integer | `20` | Maximum accepted worksheet count, once Excel support exists (`ING-03`). |
| `MAX_UNCOMPRESSED_WORKBOOK_MB` | positive integer | `500` | Maximum accepted uncompressed workbook size (expansion-bomb defense), once Excel support exists. |
| `MAX_CELL_COUNT` | positive integer | `50000000` | Maximum accepted total cell count, once parsing exists. |
| `ANALYSIS_RETENTION_HOURS` | non-negative integer (`0` = unlimited) | `0` | Will control automatic analysis retention once persistence exists (`DB-01`). |
| `BACKGROUND_WORKER_COUNT` | positive integer | `2` | Will size the bounded in-process worker pool once background jobs exist (`JOB-01`). |

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
| `LLM_MODEL` | string (unconstrained, default empty) | `""` (empty) | The exact model identifier `AI-03`'s provider requests — set this to the identifier your `llama-server` instance reports for the baseline-profile model (Qwen3.5-4B-Q4_K_M, `D-034`). |
| `LLM_TEMPERATURE` | float, `0`–`2` | `0` | Will configure model sampling temperature once a provider calls a model. |
| `LLM_CONTEXT_WINDOW` | positive integer | `8192` | Will bound the model context window once a provider calls a model. |
| `LLM_TIMEOUT_SECONDS` | positive integer | `120` | Will bound a single model call's timeout once a provider calls a model. |
| `LLM_SEND_SAMPLE_VALUES` | boolean | `false` | Will gate whether sample dataset values may ever be sent to a model, once that path exists (`CTX-02`). Off by default. |
| `LLM_MAX_SAMPLE_VALUES` | non-negative integer | `10` | Will bound how many sample values may be sent if `LLM_SEND_SAMPLE_VALUES` is enabled. |

## Security

| Variable | Type | Default | Effect |
|---|---|---|---|
| `PROMPT_INJECTION_DETECTION_ENABLED` | boolean | `true` | Will gate the prompt-injection detector once it exists (`DET-SEC-01`). |
| `MAX_TEXT_VALUE_LENGTH_FOR_ANALYSIS` | positive integer | `10000` | Will bound how much of a single text value is inspected, once detectors exist. |
| `MAX_COLUMN_NAME_LENGTH` | positive integer | `256` | Will bound accepted column-name length, once parsing exists. |

## Operational visibility

`GET /api/v1/health/ready` includes a `configuration` check confirming
`Settings` loaded successfully. Because invalid configuration already
prevents the process from starting (see above), this check can only be
observed as `"ok"` once the application is serving requests — it exists
as a real, extensible check for future in-process reconfiguration paths,
not a constant.
