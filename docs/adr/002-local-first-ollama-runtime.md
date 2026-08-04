# ADR 002: Local-First Ollama Runtime

**Status:** Accepted

## Decision

Ollama is the default live LLM runtime. It runs on the host, outside the main Docker stack.

Required providers:

- disabled
- mock
- Ollama

## Rationale

- no paid API
- simpler GPU access
- explicit privacy boundary
- test suite does not require a model

## Consequences

- users install Ollama separately for live AI
- Docker-to-host networking must be documented
- AI is optional
