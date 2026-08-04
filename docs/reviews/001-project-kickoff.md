# Engineering Review 001: Project Kickoff

**Status:** Completed  
**Purpose:** Validate product direction and implementation readiness before production code.

## Perspectives represented

- Product Owner
- Software Architect
- Frontend Lead
- Backend Lead
- AI and Data Science Lead
- QA Lead

These are structured responsibility perspectives, not claims of a staffed fictional team.

## Shared product conclusion

TrustTable should be positioned as:

> A local-first data quality investigation product for business managers, combining deterministic evidence with optional, grounded local AI interpretation.

## Product Owner findings

Strengths:

- clear user
- clear workflow
- useful without AI
- understandable business value
- visible differentiation from CSV chat tools

Risk:

- feature scope can grow too quickly

Decision:

- freeze v1 scope around the documented workflow and production boundary

## Architecture findings

Strengths:

- single-instance design
- SQLite
- bounded in-process work
- clear deterministic/AI separation
- no unnecessary distributed infrastructure

Risks:

- detector architecture and domain concepts required explicit definitions
- AI trust boundary required a dedicated subsystem

Actions completed:

- domain model added
- detector framework added
- trust-boundary ADR added

## Frontend findings

Strengths:

- appropriate technology stack
- structured investigation rather than chat
- provenance-first user experience

Risks:

- inconsistent UI if coding agents invent patterns independently
- unsafe rendering of dataset or model content

Decisions:

- feature-oriented frontend structure
- generated API contracts
- no unsafe HTML
- dedicated security finding presentation

## Backend findings

Strengths:

- clear domain services
- testable deterministic engine
- appropriate persistence and job design

Risks:

- lifecycle behavior and entities needed formal definition
- API churn without an agreed contract

Actions completed:

- domain model added
- API specification added
- retry, cancellation, deletion, and migration behavior defined

## AI and data science findings

Strengths:

- deterministic facts remain authoritative
- synthetic ground truth
- AI evaluation is not model-judge-only
- prompt injection is a meaningful flagship capability

Risks:

- detector quality must be measured
- model output must be validated beyond JSON shape

Decisions:

- exact numeric grounding
- evidence and column allow-lists
- adversarial mock-model tests
- prompt-injection detector and report section

## QA findings

Strengths:

- requirements are testable
- release blockers are explicit
- AI-disabled CI is possible

Risks:

- “fully tested” must remain a measurable standard rather than a guarantee

Decisions:

- layered tests
- browser and accessibility gates
- migration and security tests
- deterministic and AI evaluation gates

## Final kickoff decisions

1. Public hosting is post-v1.
2. Local Docker is the production delivery target.
3. Ollama is optional and host-installed.
4. AI-disabled mode is fully supported.
5. Prompt-injection handling is visible and tested.
6. Domain, API, detector, UI, security, and test boundaries are documented.
7. Production implementation begins with one backlog task at a time.

## Open questions deferred to process planning

- branch policy
- pull-request policy
- release ceremony
- issue templates
- meeting cadence
- changelog format
- semantic version automation
