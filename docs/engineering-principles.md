# TrustTable Engineering Principles

## 1. Deterministic evidence is authoritative

AI may interpret evidence. It may not replace it.

## 2. Uploaded content is untrusted

Files, filenames, worksheet names, columns, cells, descriptions, and model output are data that require validation and safe rendering.

## 3. AI assists; it does not decide

The model cannot erase findings, rewrite counts, or overrule the risk score.

## 4. Evidence precedes explanation

A finding without deterministic evidence is not a product finding.

## 5. The product works without AI

AI-disabled mode is a supported operating mode, not a degraded error screen.

## 6. Prefer the simplest architecture that satisfies the requirement

Do not add distributed infrastructure, services, frameworks, or abstractions without demonstrated need.

## 7. Domain logic is framework-independent

Core profiling, detectors, risk scoring, rules, and grounding do not depend on FastAPI, SQLAlchemy, or React.

## 8. Contracts are explicit and versioned

APIs, profiles, findings, evidence, prompts, detector configuration, and validation rules use versioned schemas.

## 9. Security behavior is visible

Prompt-injection handling, sample transmission, provider location, and output rejection are understandable to the user and report reader.

## 10. Tests are production code

Tests must be readable, deterministic, maintained, and tied to release gates.

## 11. Fail safely and informatively

Errors expose enough information to recover without exposing data, secrets, or internals.

## 12. Preserve provenance

The product distinguishes calculated, AI-assisted, user-confirmed, user-corrected, and fallback content.

## 13. Never silently modify source data

Recommendations and rules are separate from mutation.

## 14. Optimize for maintainability over cleverness

Prefer explicit modules, typed contracts, and readable control flow.

## 15. Design for bounded resource use

Every parser, detector, prompt, export, and UI list has explicit limits.

## 16. Documentation is part of the implementation

Behavior changes update the relevant requirements, ADR, or technical document.

## 17. One backlog task at a time

Small, reviewable changes reduce agent drift and regression risk.

## 18. No hidden heuristics

Thresholds and scoring logic are documented, configurable where appropriate, and recorded with analyses.

## 19. Accessibility is a release requirement

Keyboard use, focus, labels, announcements, and text-based status meaning are not optional polish.

## 20. Public claims require evidence

Performance, detector quality, security, and AI-grounding claims must cite measured project results.
