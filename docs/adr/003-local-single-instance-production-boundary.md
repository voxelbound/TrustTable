# ADR 003: Local Single-Instance Production Boundary

**Status:** Accepted

## Decision

Version 1 is a production-quality local-first, single-instance product.

Public hosting is deferred until after v1.

## Consequences

Version 1 excludes:

- authentication
- multi-tenancy
- public live inference
- anonymous rate limiting
- public retention policy
- uptime SLA

The architecture remains hostable.
