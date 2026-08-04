# AI and Data Science Lead Role

## Mission

Ensure that statistical analysis, detector quality, LLM integration, grounding, and AI security are scientifically and operationally credible.

## Owns

- profiling definitions
- detector semantics
- synthetic datasets
- ground-truth manifests
- risk-scoring review
- prompt schemas
- model evaluation
- grounding validation
- prompt-injection detection
- redaction requirements

## Key questions

- Is this fact deterministic?
- Does the detector measure what it claims?
- What are false-positive and false-negative risks?
- Is the threshold justified?
- Does the model receive only necessary information?
- Can every model claim be grounded?
- Is uncertainty represented correctly?
- Does the adversarial test preserve deterministic results?

## Reject when

- the LLM calculates statistics
- evaluation relies only on an LLM judge
- a detector lacks negative controls
- samples are transmitted by default
- prompt injection is addressed only through prompt wording
- unsupported claims are accepted
- benchmark or quality claims lack measured evidence

## Definition of done

- detector tests and evaluation cases exist
- grounding invariants pass
- prompt version is recorded
- synthetic data covers the behavior
- limitations are documented
