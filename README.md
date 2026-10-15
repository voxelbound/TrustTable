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

Then open <http://127.0.0.1:8080>, choose a `.csv` or `.xlsx` file to review before it is analyzed (or choose **Try the sales demo**), and open any finding. This is the whole product **without AI**: TrustTable's deterministic findings and evidence, plus built-in guidance for each finding — an explanation, possible business impact, a remediation suggestion and a proposed validation rule.

Optionally add a **local AI model** (`llama.cpp`, no account or API key, no Hugging Face access at runtime) for an AI-assisted version of that analysis. Every AI answer is validated, advisory, and never overrides the deterministic results. The complete Linux guide — running without AI, provisioning the GGUF model, starting `llama-server`, the environment settings, Docker versus native, verification for backend, frontend and model, and troubleshooting — is **[Install and run TrustTable on Linux](docs/installation-linux.md)**.

> A GitHub-and-GHCR-only install (no PyPI, npm or container base-image access) is supported through the **published `v0.3.0` images** (and `v0.2.0` before them): `docker-compose.release.yml` pulls them and builds nothing, and this was verified on a clean Linux host with AI off ([`docs/release-images.md`](docs/release-images.md)). `docker compose up --build` above builds the images from source and does need the base-image registry, PyPI and npm. The guide states exactly what was and was not verified.

## Project status

**Current milestone: v1.0 — Production-quality local release (active).**

`v1.0` is not released. The latest published release is `v0.3.0`, from the completed `v0.3` milestone. **`v0.3.0` is published** (tag `v0.3.0`, both `0.3.0` images on GHCR) and was verified on a clean Linux host with no GHCR credentials by a pull, start and health check with AI off. The images are unsigned, unattested and not container-scanned, and the local-AI setup was not exercised on that host. The `v0.1`, `v0.1.1`, `v0.2` and `v0.3` milestones are complete; what each delivered, with the limits stated at its completion, is in [`docs/delivery-history.md`](docs/delivery-history.md).

**What the product does today.** Each point below describes present behavior or an explicit limit. The specifications named in each point own the detail; the decisions are in `docs/decision-log.md` (D-066 to D-078) and the delivery chronology is in [`docs/delivery-history.md`](docs/delivery-history.md).

- **Workspace and a deliberate start.** Choosing a `.csv` or `.xlsx` file never starts an analysis: the Workspace stages the file and opens a Configure step that shows the file's facts, asks which worksheet to analyze when a workbook has several, reports problems that would stop the file being read, lists in plain language what TrustTable checks and shows the Local AI and privacy status. One **Run analysis** action then analyzes exactly the file you reviewed. The staged copy is short-lived and bounded, is deleted when it is run or discarded, and is referenced only by a single-use token that never appears in an address. The Workspace lists your 20 most recent analyses, each with **Open**, **Run again** and **Delete** (permanent, and asked first). A *Compare datasets* area is visible but disabled and says comparison is planned and not available. The routes and limits are in `docs/api-specification.md` and `docs/ui-specification.md`.
- **Excel support (`ING-03`, complete).** Excel (`.xlsx`) upload uses a secure standard-library parser that never evaluates formulas and refuses macro-enabled, encrypted and malformed workbooks. The documented limits (`MAX_FILE_SIZE_MB`, `MAX_ROWS`, `MAX_COLUMNS`, `MAX_WORKSHEETS`, `MAX_UNCOMPRESSED_WORKBOOK_MB`, `MAX_CELL_COUNT`) are read from the settings on every CSV and Excel parse, and with no variables set the defaults apply; lowering a limit also applies to analyses created earlier, and a later step that re-reads such a file reports a server error rather than a documented message.
- **Overview and progress.** A finished analysis opens on an Overview with the trust assessment, an *At a glance* summary (counts only), findings by severity and kind of problem, the columns with the most findings, the top three findings and the observations (*Worth knowing*). While an analysis runs, the steps are shown in plain wording with no time estimate. There are no trends and no comparison with an earlier analysis.
- **Findings review workspace.** You can work through findings in order, with a **Review** filter beside severity, category and search, a finding's position with **Previous**, **Next** and **Next unreviewed** links that follow your filters, and the same navigation by keyboard. A finding opens at once with TrustTable's built-in guidance; the optional AI explanation is prepared in the background, is saved only when it is accepted and validated, and is shown only while it is still current. Nothing is explained automatically for findings you do not open.
- **Data inspector.** A finding that points to particular rows offers **Inspect the affected rows**: a scrollable grid with affected rows and columns marked in words as well as colour and a return link to the finding with your filters intact. It is a view only: nothing seen there is sent to an AI model or added to evidence, a report or an export, cell text is shown as plain text only, and no copy of your parsed rows is kept.
- **Supporting areas and help.** An analysis groups its screens under **Review** (Overview, Findings, Observations, About this data) and **Act and Export** (Reports, Rules, Technical details). Rules belong to one analysis, are not applied to later files or other datasets and cannot be created or edited on the Rules screen; running, deleting and exporting them work as before. A **Help** link explains findings and observations, the trust assessment (worked out by fixed rules, not by AI, and not proof that the data is correct), where a statement comes from, sampled and full data, AI assistance and Rules.
- **Settings and Advanced mode.** A **Settings** screen explains **AI assistance** and lets you turn it on or off and reset it to the default, through a versioned Settings API. A setting your installation manages explicitly (`LLM_PROVIDER` in the environment or `.env`) wins and is shown as read-only with its reason; TrustTable never edits your configuration, and sending to another address stays an explicit decision of your installation. A stored "on" selects the local `llama.cpp` runtime only if your installation has set `LLM_MODEL` and the configured address is this machine. `PROMPT_INJECTION_DETECTION_ENABLED` and `ANALYSIS_RETENTION_HOURS` do nothing today, and the documentation says so. **Advanced mode** is a display choice kept in your browser only and is not a security control. The rules for the value in effect, stale-write refusal and the `.env.example` upgrade note are in `docs/configuration.md` and `docs/api-specification.md`.
- **Local AI status.** A **Local AI** screen shows, as five steps in order, whether AI assistance can work on this installation, and **Test connection** checks once whether the configured runtime on this machine answers. It sends none of your data and never shows an address, path or error text. "The runtime answered" means only that it is running, not that the model works or is suitable. Setting up a runtime happens outside TrustTable: **TrustTable does not download, install, start or configure a runtime or model**, and does not browse for models.
- **Detector catalogue (`DET-03`, closed as the Core detector catalogue, `docs/decision-log.md` D-065).** 26 detectors covering 28 of 41 catalogue entries; 13 carried by named successors. This closes the **Core** catalogue only: the 13 carried entries are **not built**, their successor items are planned with no milestone placement, and no detection is active for them, so the full catalogue is not built. Data observations are read-only, never change the trust assessment and are not sent to an AI model; a start-date and end-date relationship can be recorded but nothing reads it yet. Each detector, its limits and the catalogue mapping are in `docs/detector-framework.md` (section 16, "Closure boundary").
- **Not built, and not claimed.** Product-managed Local AI (installing or managing a runtime or model, profiles, hardware detection or acceleration) is an open, unapproved design track (`LAI-01`). There is no AI profile setting, no retention or auto-delete setting, no durable Dataset and no comparison of analyses. Standards policy and semantic category harmonization are proposed capabilities, not shipped functionality.

**UI/UX redesign outcome.** The redesign is implemented and merged. After manual end-to-end testing the human owner did not accept the resulting UI/UX outcome as meeting the intended business-application quality: substantial redesign is required, and no replacement design or redesign direction is approved yet.

**Remaining work for `v1.0`.**

- **Partly done, baselines only:** security hardening (`SEC-01`), performance benchmarks (`PERF-01`), accessibility (`A11Y-01`) and the browser matrix (`BROWSER-01`) each have a `v0.1`-scoped baseline; their full scope is open.
- **Planned:** sensitive-sample redaction (`PRIV-01`), deterministic and AI evaluation (`EVAL-01`, `EVAL-02`), migration and recovery tests (`MIG-01`), portfolio documentation (`DOC-01`) and the `v1.0` release itself (`REL-04`).
- **Known limits:** Excel formatting is ignored by design, so a date stored as a serial number is shown as that number. The Configure step previews a chosen workbook's worksheets and shape before it runs (`POST /api/v1/datasets/inspect` was superseded by the staged-upload routes and will not be built). The Playwright end-to-end suite currently holds a smoke check and the demo flow; the other scenarios in `docs/testing-strategy.md` §2.4, including Excel worksheet selection, belong to the `v1.0` test gates.

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

The backend and frontend can be started native or through Docker Compose — see [Local development](docs/local-development.md) for exact commands. The bundled deterministic demo dataset is [`demo-data/sales_demo.csv`](demo-data/sales_demo.csv).

The full deterministic pipeline (CSV and Excel parsing, type inference, profiling, detection, and risk scoring) is reachable through the running backend API (`POST /api/v1/demo/sales`, `POST /api/v1/analyses`, `GET /api/v1/analyses/{id}`, `.../status`, `.../profile`, `.../findings`, `GET .../findings/{finding_id}`, `.../evidence`, `.../row-context`, `.../column-context`, `GET .../observations/{observation_id}/row-context`, `POST .../cancel`, `POST .../retry`; the complete route list is in `docs/api-specification.md`) and through the real frontend: open the running app, choose "Try the sales demo" or your own `.csv` or `.xlsx` file on the Workspace, review it on the Configure step and press "Run analysis" to see a progress view, a trust-assessment Overview, a filterable Findings list, and — by selecting any finding — a Finding detail screen with its evidence, an explanation, possible business impact, remediation and a proposed validation rule (built-in guidance, or an AI-assisted version when a local model is configured), the affected rows in the data inspector (row-anchored findings only), or, for the prompt-injection detector's own finding, a dedicated warning presentation explaining what was detected, whether it was sent to a model, and what protections apply.

A workbook with several worksheets asks which one to analyze on the Configure step, and the Overview names the worksheet that was analyzed. Formulas are never evaluated (the stored result is read), macro-enabled (`.xlsm`), encrypted and malformed workbooks are refused, and limits on size, rows, columns and cells apply. Formatting is ignored, so a date stored as a serial number is shown as that number. [Local development](docs/local-development.md#exercising-the-deterministic-profiling-pipeline-directly) still has a reproducible way to exercise the pipeline directly in Python, without the API, if preferred.

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

The full set of engineering rules is in [Engineering principles](docs/engineering-principles.md).

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
- [Release images](docs/release-images.md)
- [Local development](docs/local-development.md)
- [Configuration](docs/configuration.md)
- [Implementation backlog](docs/implementation-backlog.md)
- [Delivery history](docs/delivery-history.md)
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
