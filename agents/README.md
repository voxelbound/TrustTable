# TrustTable Role Handbook

The files in this directory define project responsibility roles.

They are not claims that named employees or a fictional team exist. They are operating perspectives used for planning, coding-agent assignments, and structured reviews.

## Roles

- Product Owner
- Software Architect
- Backend Lead
- Frontend Lead
- AI and Data Science Lead
- QA Lead
- Coding Agent

## How to use a role

A task prompt may state:

```text
Review this change from the Backend Lead perspective using agents/backend-lead.md.
```

The role document defines:

- mission
- responsibilities
- authority
- review questions
- rejection criteria
- definition of done
- escalation boundaries

## Decision ownership

| Area | Owner | Required reviewer |
|---|---|---|
| Product scope | Product Owner | Architect |
| Architecture | Software Architect | Relevant lead |
| Backend implementation | Backend Lead | QA |
| Frontend implementation | Frontend Lead | QA |
| AI and detector behavior | AI/Data Science Lead | Architect and QA |
| Release readiness | QA Lead | Product Owner |
| Cross-cutting security | Architect | AI Lead and QA |
