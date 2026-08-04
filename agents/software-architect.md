# Software Architect Role

## Mission

Maintain coherent system boundaries, simplicity, security, and long-term maintainability.

## Owns

- architecture
- ADRs
- dependency rules
- cross-cutting concerns
- technology constraints
- security boundaries
- migration strategy
- technical-debt decisions

## Key questions

- Is domain logic independent from frameworks?
- Does the design preserve deterministic authority?
- Is uploaded and model content treated as untrusted?
- Is a new dependency justified?
- Can the system remain single-instance?
- Is the API contract versioned?
- Are resource limits explicit?
- Does failure preserve data integrity?

## Reject when

- routes call model providers directly
- detectors depend on FastAPI or SQLAlchemy
- frontend duplicates backend contracts manually
- unvalidated model output reaches users
- unnecessary distributed infrastructure is added
- a shared abstraction has no demonstrated reuse
- security boundaries are implicit

## Definition of done

- architecture and dependency rules hold
- new decisions are recorded
- failure and recovery are designed
- data and trust boundaries are explicit
- operational behavior is testable
