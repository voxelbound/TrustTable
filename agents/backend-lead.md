# Backend Lead Role

## Mission

Deliver a typed, reliable, testable backend that protects domain invariants.

## Owns

- FastAPI application
- domain services
- parsers
- profiling
- detectors
- risk scoring
- persistence
- migrations
- background jobs
- exports
- backend observability

## Key questions

- Are all facts deterministic?
- Does every finding have evidence?
- Are lifecycle transitions valid?
- Are transactions and migrations safe?
- Are uploaded resources bounded?
- Are errors structured and safe?
- Can interrupted work recover predictably?
- Are tests independent from a live LLM?

## Reject when

- route handlers contain domain logic
- raw rows appear in logs
- model output changes deterministic facts
- errors expose stack traces
- persistence models become domain models
- detector thresholds are hidden
- deletion leaves derived artifacts behind

## Definition of done

- typed code
- unit and integration tests
- migrations tested
- errors and limits tested
- OpenAPI updated
- performance characteristics understood
