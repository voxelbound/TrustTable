# Security Policy

## Supported versions

Security fixes are applied to the latest released version and the active development branch.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose data, execute untrusted content, bypass model trust boundaries, or compromise a deployment.

Use GitHub's private vulnerability reporting feature when enabled. Until then, contact the repository owner through the private contact method listed on their GitHub profile.

Include:

- affected version or commit
- reproduction steps
- expected and observed behavior
- possible impact
- relevant logs with sensitive values removed
- suggested mitigation, when known

## Security boundaries

TrustTable treats all uploaded content as untrusted, including:

- filenames
- worksheet names
- column names
- cell values
- user-provided descriptions
- LLM output

Deterministic analysis is authoritative. LLM output cannot remove deterministic findings, replace risk scores, or introduce unsupported facts.

## Known version 1 boundary

Version 1 is a local-first, single-instance application. It is not a multi-tenant SaaS service.

A future public demonstration will require a separate security and operations review before deployment.
