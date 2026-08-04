# Contributing to TrustTable

TrustTable is initially developed through small, dependency-ordered backlog tasks.

## Working rules

1. Read `docs/product-requirements.md`.
2. Read the complete backlog task and its dependencies.
3. Read relevant ADRs.
4. Implement one task at a time.
5. Avoid unrelated refactoring and infrastructure.
6. Add or update tests.
7. Run formatting, linting, type checking, and relevant tests.
8. Update documentation when behavior or configuration changes.

## Branches and commits

Use short-lived branches for substantial changes.

Suggested branch names:

```text
feat/FND-01-repository-foundation
feat/DEMO-01-sales-generator
fix/prompt-injection-rendering
docs/update-testing-strategy
```

Suggested commit prefixes:

- `feat:` functionality
- `fix:` defect correction
- `docs:` documentation
- `test:` test changes
- `refactor:` behavior-preserving restructuring
- `chore:` repository or tooling maintenance
- `security:` security hardening

## Pull-request expectations

A pull request should state:

- backlog task
- implementation summary
- design decisions
- files changed
- commands run
- test results
- known limitations
- screenshots for user-visible changes

No pull request should be merged while required CI checks fail.

## Scope control

Do not introduce the following without a new approved requirement or ADR:

- Redis
- Celery
- Kafka
- Kubernetes
- microservices
- authentication
- multi-tenant behavior
- paid model APIs
- automatic dataset repair
- autonomous agents
- GraphQL
- Redux
- WebSockets

## Security

Never commit:

- `.env`
- API keys
- personal datasets
- uploaded files
- SQLite runtime databases
- model files
- raw prompts containing private data
- logs containing dataset values

Report security issues using the process in `SECURITY.md`.
