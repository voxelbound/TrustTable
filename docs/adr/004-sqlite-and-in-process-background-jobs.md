# ADR 004: SQLite and In-Process Background Jobs

**Status:** Accepted

## Decision

Use SQLAlchemy 2, Alembic, SQLite, and a bounded in-process worker pool.

## Rationale

This satisfies local persistence, migration, cancellation, retry, and restart behavior without distributed infrastructure.

## Consequences

- one application instance
- interrupted active jobs become failed after restart
- no Redis or Celery
- backup and restore use the mounted volume
