# Engineering Review 002: Architecture Baseline

**Status:** Accepted

## Reviewed

- system boundaries
- backend layering
- frontend architecture
- API generation
- persistence
- jobs
- AI provider boundary
- security controls

## Accepted architecture

- React SPA served as static assets
- versioned FastAPI API
- domain-independent analysis engine
- SQLAlchemy 2 and Alembic
- SQLite mounted volume
- bounded in-process workers
- optional host Ollama
- explicit detector registry
- versioned schemas
- generated frontend API types

## Rejected for v1

- microservices
- Kubernetes
- Redis
- Celery
- GraphQL
- WebSockets
- Redux
- SSR
- public live inference
- authentication
- multi-tenancy

## Required architecture tests

- dependency-boundary checks where practical
- OpenAPI generation drift
- migration tests
- restart behavior
- Ollama-disabled behavior
- model-output grounding
- deletion integrity

## Outcome

Architecture approved for foundation implementation.
