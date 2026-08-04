# ADR 005: Frontend SPA Architecture

**Status:** Accepted

## Decision

Use:

- React
- strict TypeScript
- Vite
- React Router Data Mode
- TanStack Query
- React Hook Form
- Tailwind CSS
- selective accessible primitives
- OpenAPI-generated types
- openapi-fetch
- npm

Do not use SSR, Redux, GraphQL, or WebSockets in v1.

## Consequences

- static production frontend
- FastAPI remains the only application server
- URL state is shareable
- server state remains in TanStack Query
- API drift is checked in CI
