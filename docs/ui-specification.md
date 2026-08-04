# TrustTable UI Specification

## 1. Design intent

TrustTable should look and behave like a serious business investigation tool.

It must be:

- calm
- evidence-focused
- manager-first
- accessible
- explicit about provenance
- usable without data-science terminology
- usable with AI disabled

It must not be designed as a chatbot.

## 2. Technology

- React
- strict TypeScript
- Vite
- React Router Data Mode
- TanStack Query
- React Hook Form
- Tailwind CSS
- selective accessible primitives
- `openapi-typescript`
- `openapi-fetch`
- npm and committed `package-lock.json`

Testing:

- Vitest
- Testing Library
- user-event
- MSW
- Playwright
- axe-core

## 3. Routes

```text
/
├── /analyses/new
└── /analyses/:analysisId
    ├── /overview
    ├── /context
    ├── /findings
    ├── /findings/:findingId
    ├── /rules
    ├── /report
    └── /technical
```

The analysis layout shows:

- dataset name
- status
- AI and privacy status
- navigation
- cancel or retry where applicable
- delete action

## 4. Screen definitions

### 4.1 Start

Contents:

- drag-and-drop upload
- file picker
- sales demo action
- file limits
- privacy status
- AI status
- model location
- sample-value setting

### 4.2 File review

Show:

- sanitized filename
- size
- format
- worksheet selector
- estimated shape where available
- warnings
- analyze action

### 4.3 Progress

Show named stages, not only a spinner.

Controls:

- cancel
- retry after failure
- return to start

Progress and errors must be announced to assistive technology.

### 4.4 Context

Editable fields:

- domain
- row grain
- transaction key
- business date
- revenue measure
- currency behavior
- negative quantity behavior

Every field shows provenance:

- Calculated
- AI interpretation
- Confirmed by user
- Corrected by user
- Deterministic fallback

### 4.5 Overview

Order:

1. trust assessment
2. top three findings
3. immediate actions
4. remaining finding summary
5. dataset summary
6. technical links

### 4.6 Findings

Filters stored in the URL:

- severity
- category
- review state
- column
- search
- sort
- page

Use pagination or bounded incremental loading.

### 4.7 Finding detail

Sections:

- observation
- possible business impact
- evidence
- representative examples
- remediation
- validation rule
- review controls
- technical metadata

### 4.8 Prompt-injection warning

Dedicated presentation:

- title: Potential prompt-injection content detected
- category: AI processing security
- affected field
- truncated escaped sample
- sent-to-model status
- model location
- protection checklist
- rejected-output status
- cautious explanation

The UI must not claim malicious intent as fact.

### 4.9 Rules

Show:

- business description
- enabled state
- current pass/fail count
- editable supported parameters
- expandable YAML or JSON
- export action

### 4.10 Report

Show:

- report preview
- included sections
- generation status
- Markdown download
- JSON/YAML rule downloads

### 4.11 Technical details

Expandable technical information:

- profile metrics
- detector IDs and versions
- thresholds
- prompt and model metadata
- timings
- sampled/full-data labels

## 5. Component architecture

### UI primitives

- Button
- Input
- Select
- Textarea
- Dialog
- Badge
- Alert
- Tabs
- Progress
- Skeleton
- Table
- Pagination

### Domain components

- TrustAssessment
- FindingSeverity
- FindingEvidence
- ProvenanceBadge
- AnalysisStageProgress
- AIPrivacyStatus
- PromptInjectionWarning
- ValidationRulePreview
- ReviewControls

### Dependency direction

```text
routes → features → API/domain/UI
features → API/domain/UI
UI primitives → no route or feature imports
domain → no React or API-client imports
```

## 6. State

### Server state

TanStack Query owns:

- analysis
- status
- profile
- context
- questions
- findings
- rules
- report metadata

Poll only during active stages.

### URL state

URL search parameters own:

- filters
- sort
- page
- selected finding view

### Form state

React Hook Form owns:

- upload options
- context correction
- guided questions
- review notes
- rule parameters

### Local UI state

React local state owns:

- open dialogs
- expanded panels
- temporary disclosure state

No Redux or Zustand in v1.

## 7. Error behavior

Layers:

1. application error boundary
2. route error boundary
3. inline query or mutation errors

Do not expose stack traces.

Uploads do not retry automatically.

Safe GET requests may retry transient failures.

## 8. Rendering security

- never use `dangerouslySetInnerHTML`
- render dataset values as text
- sanitize any supported Markdown
- never auto-link arbitrary dataset text
- truncate suspicious values outside detail views
- escape formula-like strings
- never execute spreadsheet content
- show full suspicious values only after deliberate user action

## 9. Responsive behavior

Primary target: desktop.

Required usability:

- desktop
- tablet
- phone

Test widths:

- 360 px
- 768 px
- 1440 px

Dense tables may become stacked records on narrow screens.

## 10. Accessibility

Release requirements:

- keyboard completion of the main workflow
- visible focus
- correct labels
- logical headings
- live announcements
- no color-only meaning
- textual severity and confidence
- no serious or critical automated accessibility violations

## 11. Frontend file structure

```text
frontend/
├── src/
│   ├── app/
│   ├── routes/
│   ├── features/
│   ├── components/
│   │   ├── ui/
│   │   ├── layout/
│   │   └── provenance/
│   ├── api/
│   │   ├── generated/
│   │   ├── client.ts
│   │   ├── errors.ts
│   │   └── queries/
│   ├── domain/
│   ├── lib/
│   │   ├── formatting/
│   │   ├── accessibility/
│   │   └── security/
│   ├── styles/
│   └── test/
└── e2e/
```
