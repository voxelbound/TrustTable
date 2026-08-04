# ADR 007: Explicit Detector Framework

**Status:** Accepted

## Decision

Use a framework-independent, explicitly registered detector catalogue.

Every detector has:

- stable ID
- version
- metadata
- configuration schema
- declared input requirements
- deterministic evidence output
- tests
- documented limitations

## Rationale

Detectors are the central extensibility point. A uniform contract prevents inconsistent implementations and supports evaluation.

## Consequences

- explicit registry in v1
- no dynamic plugin discovery
- evidence precedes findings
- detector changes require version review
