# TrustTable

TrustTable is a local-first, AI-assisted data quality investigator for business datasets.

It combines deterministic profiling and rule-based detection with evidence-grounded LLM interpretation. Calculated facts remain authoritative; AI is used to infer context, ask focused questions, explain findings, recommend remediation, and describe validation rules.

## Project status

TrustTable has completed its repository foundation (**FND-01**), typed configuration (**FND-02**), continuous integration (**FND-03**), common API errors (**FND-04**), the OpenAPI frontend contract pipeline (**FND-05**), the synthetic sales generator (**DEMO-01**), the parsing contracts (**ING-01**), the secure CSV parser (**ING-02**), the profiling schemas (**PROF-01**), type inference (**PROF-02**), core profiling (**PROF-03**), the detector interface (**DET-01**), the initial detector set (**DET-02** — all 12 detectors: duplicate rows, empty columns, excessive missing values, missing likely identifiers, inconsistent capitalization, leading/trailing whitespace, future dates, negative measures, invalid percentages, line-total mismatch, suspiciously constant columns, and extreme outliers), the LLM input/output trust boundaries (**SEC-02** — the untrusted-data envelope, safe prompt builder, and model-output validator; no real LLM provider is wired in yet), the prompt-injection risk detector (**DET-SEC-01** — `security.possible_llm_prompt_injection`, the required AI-processing-security detector, completing the detector catalogue at 13/13), deterministic risk scoring (**RISK-01** — per-finding priority scores and a four-label dataset trust assessment, computed with no AI/LLM input path at all), the initial analysis API (**API-01** — the in-memory analysis-orchestration engine composing parsing/profiling/detection/scoring into one create-then-run pipeline over the bundled demo dataset, exposed over real `/api/v1` HTTP routes: `POST /demo/sales`, `GET /analyses/{id}`, `GET /analyses/{id}/status`, `GET /analyses/{id}/profile`, `GET /analyses/{id}/findings`, `POST /analyses/{id}/cancel`), and a first slice of the basic investigation UI (**UI-01**, partial — a real Start screen with a working sales-demo action, a named-stage progress view, an Overview screen (trust assessment, top findings, dataset summary), and a Findings list with severity/category/search filtering, all reading the running backend API; finding detail, evidence display, and the dedicated prompt-injection-warning screen remain open, since the current API has no per-finding-detail or evidence-retrieval endpoint yet), and Docker Compose production-configuration hardening (**REL-01**, scoped — both services now restart automatically after an unexpected exit; SBOM generation and container image scanning are explicitly deferred to **SEC-01**, a later backlog item, not part of this package). TrustTable has not yet reached **v0.1 — the deterministic vertical slice** in full: the basic full-stack UI (`UI-01`) remains a disclosed partial slice, so v0.1 completion is still pending that remaining work.

The product, domain model, API boundaries, detector framework, frontend architecture, testing strategy, threat model, release plan, and implementation backlog have been defined before production implementation begins. A runnable backend and frontend skeleton, Docker/Nginx deployment, and baseline test tooling now exist; no product features are implemented yet.

The first production target is a local, single-instance application that:

- runs through Docker
- analyzes CSV and Excel files
- remains useful without an LLM
- optionally uses a locally downloaded model through Ollama
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
backend API directly (`POST /api/v1/demo/sales`, `GET
/api/v1/analyses/{id}`, `.../status`, `.../profile`, `.../findings`,
`POST .../cancel`) and through a first slice of the real frontend: open
the running app and choose "Try the sales demo" on the Start screen to
see a progress view, a trust-assessment Overview, and a filterable
Findings list. Finding detail, evidence display, and the dedicated
prompt-injection-warning screen are not built yet (`UI-01` remains
partial — the current API has no per-finding-detail or evidence-
retrieval endpoint). Generic file upload (arbitrary CSV/Excel analysis
creation, as opposed to the bundled demo dataset) is also not yet
exposed — the Start screen's upload control is present but disabled.
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
- Local Ollama integration must not require an API key.
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

- [Local development](docs/local-development.md)
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
- Ollama, disabled, and mock model providers

## Supported production boundary

Version 1 is a production-quality, local-first, single-instance application.

Formally supported development and deployment environments:

- Linux x86-64
- Windows 11 with WSL2 and Docker Desktop

Current Chrome, Edge, Firefox, and Safari are target browsers. Native Windows execution without WSL is not a version 1 requirement.

## License

Apache License 2.0.
