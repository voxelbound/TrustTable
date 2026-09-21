# Install and run TrustTable on Linux

TrustTable is a local-first application. This guide takes a Linux machine from
nothing to a running TrustTable, first **without any AI**, then **with a local
AI model** served by `llama.cpp`. Nothing here needs a paid account, an API
key, or a hosted service.

Formally supported Linux target: **Linux x86-64** with Docker Engine
(`README.md`, "Supported production boundary").

> **What has and has not been verified.** Every port, setting, file and
> endpoint named below is checked against the repository by an automated
> documentation test, and the model-facing behavior is proven with a stub
> `llama-server`. The published `v0.2.0` release was also installed on a clean
> Linux host with no GHCR credentials and started with AI off. A run with a real
> model on a clean host is **not** part of this guide's evidence; see
> [Restricted-network installs](#restricted-network-installs) for exactly what
> was and was not covered.

## 1. Quick start (no AI)

You need:

- **Docker Engine 20.10 or newer** with the Compose v2 plugin
  (`docker compose version` must work; the standalone `docker-compose` binary
  is not supported).
- **git**, and network access to GitHub and to the container/package
  registries the build uses. A host that can reach only GitHub and GHCR should
  install the published images instead of building (see
  [Restricted-network installs](#restricted-network-installs)).

```sh
git clone https://github.com/voxelbound/trusttable.git
cd trusttable
docker compose up --build
```

Open **<http://127.0.0.1:8080>** and choose **Try the sales demo**, or upload a
`.csv` file. That is the whole product with AI switched off: findings, evidence,
a trust assessment, and — for every finding — an explanation, possible business
impact, a remediation suggestion and a proposed validation rule, all produced
by TrustTable's built-in deterministic guidance. `LLM_PROVIDER` defaults to
`disabled`, so nothing contacts any model.

Stop it with `docker compose down`.

### Check that it works

```sh
curl -s http://127.0.0.1:8000/api/v1/health/live
curl -s http://127.0.0.1:8000/api/v1/health/ready
curl -s http://127.0.0.1:8000/api/v1/version
curl -sI http://127.0.0.1:8080/
```

The three backend calls return JSON; the last returns `HTTP/1.1 200 OK` from the
Nginx-served frontend. Only ports `8000` (backend) and `8080` (frontend) are
published.

## 2. Native (no Docker) instead

Use this when you would rather not run containers.

- **Python 3.14** and [`uv`](https://docs.astral.sh/uv/)
- **Node.js 24 (LTS)** and npm

```sh
# backend, port 8000
cd backend
uv sync
uv run uvicorn trusttable_backend.main:app --port 8000
```

The Vite dev server does not proxy the API, so for the full UI against a native
backend use Docker Compose. Native execution is intended for development; see
[`docs/local-development.md`](local-development.md).

## 3. Turning on local AI (llama.cpp)

TrustTable can ask a **local** model to write the AI-assisted analysis of a
finding: an explanation, possible business impact, remediation advice and a
proposed validation rule. AI is optional and additive: deterministic findings,
evidence, severity and the trust assessment never depend on it, and every AI
answer is validated before it is shown (otherwise the built-in guidance stays).

The pieces:

| Piece | Where it runs | Port |
|---|---|---|
| TrustTable frontend | Docker container | `8080` |
| TrustTable backend | Docker container | `8000` |
| `llama-server` (`llama.cpp`) | **on the host**, started by you | `8081` |
| GGUF model file | a directory on the host, read only by `llama-server` | — |

`llama-server` is inference infrastructure only. TrustTable is the sole
user-facing application; run `llama-server` with `--no-webui` and never send
users to it (`docs/decision-log.md` D-036).

### 3.1 Install `llama-server`

Follow the official instructions at <https://github.com/ggml-org/llama.cpp>
(a release binary or a source build). TrustTable neither bundles nor installs
it. Check it runs:

```sh
llama-server --version
```

### 3.2 Provision the GGUF model — no Hugging Face access at runtime

The documented baseline is **Qwen3.5-4B-Q4_K_M** on the CPU-oriented profile
(`docs/decision-log.md` D-034, D-035). TrustTable does not download, bundle or
redistribute model weights, and never contacts Hugging Face (or anything else)
to obtain one. **Where the file lives is up to you** — TrustTable never reads
it; only `llama-server` does.

1. Obtain the `.gguf` file once, on any machine, from its publisher, and verify
   its checksum against the source you got it from. Review the licence for your
   intended use — that check is yours, not TrustTable's.
2. Copy it to the Linux host, for example `/opt/trusttable/models/`.
   Copying over `scp`, a USB drive or an internal artifact store all work, so a
   host with **no Hugging Face access at runtime** is fine.

### 3.3 Start `llama-server`

```sh
llama-server \
  --model /opt/trusttable/models/Qwen3.5-4B-Q4_K_M.gguf \
  --host 0.0.0.0 \
  --port 8081 \
  --ctx-size 8192 \
  --n-gpu-layers 0 \
  --no-webui
```

`--n-gpu-layers 0` is the baseline CPU profile; the accelerated/GPU tier is a
separate, deferred decision (D-035) and a `llama.cpp` tuning matter outside this
guide.

> **Why `--host 0.0.0.0`, and the safe alternative.** The backend runs in a
> container, so it reaches the host over the Docker bridge. A `llama-server`
> bound only to `127.0.0.1` cannot be reached from a container. Binding
> `0.0.0.0` also exposes an unauthenticated inference server to your network.
> Prefer binding to the Docker bridge address only
> (`--host 172.17.0.1`, the default `docker0` address — confirm yours with
> `ip -4 addr show docker0`), or block port `8081` from outside the machine
> with your firewall.

Confirm it is serving (from the host):

```sh
curl -s http://127.0.0.1:8081/health
curl -s http://127.0.0.1:8081/v1/models
```

### 3.4 Point TrustTable at it

Create a `.env` file in the repository root (Compose and the native backend read
it automatically; copy `.env.example` as a starting point):

```sh
LLM_PROVIDER=llama_cpp
LLM_BASE_URL=http://host.docker.internal:8081
LLM_MODEL=Qwen3.5-4B-Q4_K_M
LLM_TIMEOUT_SECONDS=300
```

- `host.docker.internal` resolves inside the backend container because
  `docker-compose.yml` maps it to the host gateway (Docker Engine on Linux does
  not define that name by itself). Running the backend natively instead? Use
  `LLM_BASE_URL=http://127.0.0.1:8081`.
- `LLM_MODEL` is a model **name**, not a path. A path also works, but TrustTable
  never shows it: the UI and the API display only a label such as
  `Local AI · llama.cpp · Qwen3.5 4B (Q4_K_M)`.
- `LLM_TIMEOUT_SECONDS`: the structured analysis is a longer answer than a
  single sentence. On CPU-only hardware allow minutes, not seconds.
- Not settings you need: the context window is `llama-server`'s `--ctx-size`;
  `LLM_TEMPERATURE`, `LLM_CONTEXT_WINDOW`, `LLM_SEND_SAMPLE_VALUES` and
  `LLM_MAX_SAMPLE_VALUES` are not applied by the backend today
  ([`docs/configuration.md`](configuration.md)). Dataset sample values are never
  sent to a model.

Restart the backend so it reads the file:

```sh
docker compose up -d --build
```

### 3.5 Verify all three links: backend, frontend, model

1. **Backend** — `curl -s http://127.0.0.1:8000/api/v1/health/ready`
2. **Frontend** — open <http://127.0.0.1:8080>.
3. **Model connectivity from the container** —
   `docker compose exec backend python -c "import urllib.request as u; print(u.urlopen('http://host.docker.internal:8081/health', timeout=5).status)"`
   prints `200`.
4. **End to end** — create an analysis and read one finding's analysis:

   ```sh
   curl -s -X POST http://127.0.0.1:8000/api/v1/demo/sales
   # note "analysis_id" in the response, then:
   curl -s http://127.0.0.1:8000/api/v1/analyses/<analysis_id>/findings/0/explanation
   ```

   `"ai_call_status": "attempted_accepted"` and an `ai_provenance` naming
   `Local AI`, `llama.cpp` and your model mean the model answered and its answer
   passed validation. In the UI, open **Findings → any finding**: the
   provenance line under *Explanation* reads
   `AI interpretation — Local AI · llama.cpp · Qwen3.5 4B (Q4_K_M)`.

### 3.5.1 What the four sections are

| Section | Shown when AI answered | Shown otherwise |
|---|---|---|
| Explanation | the model's grounded explanation | the built-in explanation |
| Possible business impact | potential impacts, each with the condition it depends on and a label TrustTable derives — *Conditional* or *Informed by your confirmed context* (never "Evidence-backed") | conditional built-in statements |
| Remediation | advice to a person; TrustTable never changes your data | built-in advice |
| Validation rule | a **proposed** rule, *not active*, never run or enforced | a built-in proposal |

Context you confirmed on the **Context** screen and then finalized is added to
the model's grounding. Values TrustTable merely *inferred* are never sent.

## 4. Docker Compose versus native — assumptions

| | Docker Compose | Native |
|---|---|---|
| Backend and frontend | containers (`docker-compose.yml`) | `uv` + Node on the host |
| Reaching `llama-server` | `http://host.docker.internal:8081` (mapped to the host gateway) | `http://127.0.0.1:8081` |
| `llama-server` bind address | must be reachable from the Docker bridge | `127.0.0.1` is enough |
| `.env` | repository root, optional | repository root, optional |

## 5. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `docker compose` says `unknown shorthand flag` or command not found | Install the Docker Compose v2 plugin; `docker-compose` (v1) is unsupported. |
| Finding Detail says *"no AI provider is configured"* | `LLM_PROVIDER` is still `disabled` (or `.env` was not picked up). Set it and restart. |
| *"an AI attempt … could not complete"* | The backend could not reach or wait for `llama-server`. Check step 3 above; raise `LLM_TIMEOUT_SECONDS`; confirm `llama-server` is bound to an address the container can reach (§3.3). |
| `Could not resolve host: host.docker.internal` inside the container | Use the Compose file in this repository (it maps the name); on an older Docker Engine (< 20.10) upgrade. |
| *"an AI attempt … did not produce a usable result"* | The model answered but its answer failed validation, so the built-in guidance is shown — by design. A small or heavily quantized model may need a second try or a larger model; deterministic results are unaffected. |
| Everything is slow | CPU inference on a 4B model takes time per finding. Only the finding you open is analysed. |
| Port `8080` or `8081` already in use | Another program holds it; stop it, or change `llama-server`'s `--port` and `LLM_BASE_URL` together. |

## Restricted-network installs

The target: **a fresh Linux host that can reach GitHub and the GitHub Container
Registry (GHCR) and has a locally provisioned GGUF file, and needs no Hugging
Face access at runtime.**

**What works**

- **Model provisioning without Hugging Face:** yes. The GGUF is copied to the
  host by any means (§3.2); TrustTable and `llama-server` never fetch it.
- **Running with no internet at all after installation:** yes, once images are
  pulled or built and the model is in place — TrustTable calls no external
  service.
- **A GitHub-and-GHCR-only install of the published release, with AI off:** yes,
  verified for `v0.2.0` (below).

**Limits — stated, not glossed over**

- **Building from source needs more than GitHub and GHCR.** `docker compose up
  --build` **builds both images from source**. That build needs the container
  base-image registry, PyPI (Python dependencies via `uv`) and the npm registry
  (frontend dependencies) — none of which a GitHub-and-GHCR-only host can reach.
  Such a host should use the published images below.
- The containerized `llama.cpp` server image is likewise not part of the
  supported path here; `llama-server` is run on the host as described above.
- The published images are **unsigned**, carry **no provenance or SBOM
  attestation**, and have **not been container-scanned**.

**Pull-only install — verified on a clean Linux host for `v0.2.0`**

The repository contains the pull-only path
([`docs/release-images.md`](release-images.md)): `docker-compose.release.yml`,
which runs published images with no build step, and a workflow that publishes
them when a maintainer pushes a version tag. The `v0.2.0` images were published
that way, and the release was then installed on a clean Linux host with only
GitHub and GHCR access and **no GHCR credentials**:

```sh
git clone --branch v0.2.0 --depth 1 https://github.com/voxelbound/trusttable.git
cd trusttable
TRUSTTABLE_VERSION=0.2.0 docker compose -f docker-compose.release.yml pull
TRUSTTABLE_VERSION=0.2.0 docker compose -f docker-compose.release.yml up -d --no-build
curl -s http://127.0.0.1:8000/api/v1/health/live
curl -s http://127.0.0.1:8000/api/v1/health/ready
curl -s http://127.0.0.1:8000/api/v1/version
curl -sI http://127.0.0.1:8080/
TRUSTTABLE_VERSION=0.2.0 docker compose -f docker-compose.release.yml down
```

On that host no TrustTable images were present beforehand and `docker logout
ghcr.io` had removed any credentials. Both
`ghcr.io/voxelbound/trusttable-backend:0.2.0` and
`ghcr.io/voxelbound/trusttable-frontend:0.2.0` pulled, the backend became healthy,
`health/live` returned `{"status":"alive"}`, `health/ready` reported the process and
configuration checks OK, `version` reported `"application_version":"0.2.0"`, the
frontend answered `HTTP/1.1 200 OK`, and `down` removed the containers and the network
cleanly. The release workflow runs the same credential-free pull and start after
every tag publish.

`TRUSTTABLE_VERSION` is required (there is no `latest`), and the version the
backend reports equals it. For a later release, substitute its version.

**What that run did not cover**

- **The local-AI setup.** `llama-server` on the host, a provisioned GGUF file and
  the model connectivity check in §3.5 were **not exercised** on the clean host.
  The `.env` file and §3 apply to this stack as well (use
  `-f docker-compose.release.yml` on the `docker compose` commands), but that is
  documented, not verified there; the model-facing behavior is proven only by the
  automated tests with a stub `llama-server`.
- **The demo analysis and any UI flow** beyond the frontend answering.
- **Any host that is not Linux x86-64:** only `linux/amd64` images are published.
- **Local-AI reliability and speed.** How reliably a real local model fills the
  structured analysis, how long a finding takes, and a suitable
  `LLM_TIMEOUT_SECONDS` were **not measured** for `v0.2` (that qualification was
  waived, `docs/decision-log.md` D-044). Treat the timeout values in this guide as
  unmeasured guidance and raise it on slow machines.

## See also

- [`docs/release-images.md`](release-images.md) — image names, tags and the publish workflow.
- [`docs/local-development.md`](local-development.md) — native development, tests.
- [`docs/configuration.md`](configuration.md) — every setting.
- [`README.md`](../README.md) — project overview.
