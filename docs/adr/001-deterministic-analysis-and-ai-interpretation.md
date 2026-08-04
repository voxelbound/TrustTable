# ADR 001: Deterministic Analysis and AI Interpretation

**Status:** Accepted

## Decision

All dataset facts and risk scores are calculated by deterministic code.

AI is limited to context inference, clarification, explanation, remediation, supported rule selection, and summaries.

## Consequences

- findings remain reproducible
- AI output can be validated
- AI-disabled mode remains useful
- the LLM cannot erase evidence
- more domain and detector code is required
