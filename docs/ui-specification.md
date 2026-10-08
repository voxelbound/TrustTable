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
/                          (Workspace; UX-02)
├── /analyses/new          (redirects to /; UX-02)
├── /configure             (Configure; UX-02; the staged reference is kept in
│                           tab-scoped session storage, never in the address)
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

**Implemented (`UI-03` slice 1):** the analysis layout shows these controls
in every state. *Cancel analysis* appears only while the status response
says the analysis is cancellable; *Retry analysis* only when it is
retryable (a failed analysis) and opens the new attempt, leaving the
original untouched; *Delete analysis* is always available, asks for
confirmation in an accessible dialog that states the removal is permanent
and cannot be undone, and returns to the start screen. Failures are shown
inline and the page stays put.

## 4. Screen definitions

### 4.1 Start (the Workspace, `UX-02`, `docs/decision-log.md` D-068)

**Implemented (`UX-02`).** `/` is the Workspace. Choosing a file (picker or drop) never
starts an analysis: it stages the file and opens the Configure step (section 4.2). A file
that cannot be read at all is not stored; the Workspace then lists the plain-language
problems and offers to choose another file. The Workspace also offers the sales demo as a
separate, explicitly labelled action that starts the demo analysis when pressed, shows
Local AI and privacy status from `GET /ai/status`, and shows a visible but disabled
*Compare datasets* area stating that comparison is planned and not implemented. The
page header carries Home and a disabled Compare entry; Analyses, Settings and Help are not
shown until their slices ship, because nothing unbuilt is presented as available
(section 12.1). Recent analyses, reopen, rerun and the exact-file notice belong to
`UX-03`.

Contents of the original Start screen (kept where still true):

- drag-and-drop upload
- file picker
- sales demo action
- file limits
- privacy status
- AI status
- model location
- sample-value setting

### 4.2 File review (the Configure step, `UX-02`, `docs/decision-log.md` D-068)

**Implemented (`UX-02`).** `/configure` replaces the former inline worksheet chooser. The
staged reference lives in `sessionStorage` (tab-scoped, cleared when the staged file is
run or discarded), so a reload keeps the step and the address never carries it. With no
reference, `/configure` returns to the Workspace. It shows, from `POST
/staged-uploads/inspect`:

- the sanitized filename, size, format and (when known) rows and columns;
- for a workbook, a worksheet chooser; a worksheet is preselected only when the workbook
  has exactly one visible sheet, otherwise nothing is preselected and Run stays
  unavailable until the user chooses; worksheet names are plain text;
- readability problems (for example a file that is not UTF-8 text) as a blocking error
  announced to assistive technology, with Run unavailable, and non-blocking notices;
- a short, grouped, business-language summary of what TrustTable checks (no detector
  names; a disclosure for more detail). There are no category or detector on/off
  controls: the standard analysis always runs;
- Local AI status (assistance is optional and separate from the deterministic checks) and
  a privacy statement, both from `GET /ai/status`;
- the time until which the staged copy is kept (from `expires_at`), stated in plain
  words;
- one *Run analysis* action, which analyses exactly the staged bytes, and *Choose a
  different file*, which discards the staged copy.

If staging is refused because too many files are already waiting (`409 STAGING_FULL`),
the Workspace says so in plain words, that waiting files are kept for up to the stated
minutes, and that the user can finish or discard a file waiting in another tab, or wait. A Run that is refused
because the chosen worksheet still has a blocking problem shows the same problem text
that the inspection showed and does not spend the staged file.

If the staged copy has expired or was already used, the screen says the file is no longer
available, that staged files are kept only briefly, and offers to choose it again. No
content hash is shown. The summary of what is checked comes from the `checks` field of
the staged-upload resource, which the server derives from the categories of the
registered detectors (one group per category, in business wording, never detector
names), so it cannot name a check that does not exist; a test fails when a category has
no group.

Original File review contract (superseded in part by the above):

Show:

- sanitized filename
- size
- format
- worksheet selector
- estimated shape where available
- warnings
- analyze action

**Implemented subset (`ING-03`, `D-052`):** there is no separate File review
screen yet. The Start screen accepts `.csv` and `.xlsx`; when a workbook has
several worksheets the API refuses it with `WORKSHEET_REQUIRED` and the
names, and the Start screen then shows an inline worksheet chooser (nothing
is pre-selected, so the user always chooses) and uploads the same file with
the picked worksheet. Worksheet names come from the file and are shown as
plain text. The estimated shape and per-file warnings need the not-yet-built
`POST /datasets/inspect` (`docs/api-specification.md` §7). The Overview and
Technical details screens name the worksheet that was analyzed.

### 4.3 Progress

Show named stages, not only a spinner.

Controls:

- cancel
- retry after failure
- return to start

Progress and errors must be announced to assistive technology.

### 4.4 Context

**Reachability (`docs/decision-log.md` D-037, `v0.2`):** reachable
after analysis completion, alongside Overview/Findings — not a
blocking pre-step. Confirming/correcting context and finalizing it
triggers optional, additive enrichment (AI interpretation/explanations)
over the already-`completed` deterministic analysis; it never gates or
re-runs deterministic detection. Not yet implemented — see
`docs/implementation-backlog.md`'s `UI-02` entry.

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
- row context (row-anchored findings only)
- remediation
- validation rule
- review controls
- technical metadata

**Analysis sections (`AI-08`, `docs/decision-log.md` D-040).** Under the
observation, one provenance line and the three sections *possible
business impact*, *remediation* and *validation rule* render from the same
analysis and must stay distinguishable from one another and from
deterministic evidence:

- the provenance line says either "AI interpretation — Local AI ·
  llama.cpp · Qwen3.5 4B (Q4_K_M)" (human-readable labels only; **never**
  a filesystem path) or "Built-in TrustTable guidance (no AI)" with the
  reason no AI result is shown;
- each business-impact statement is a *potential* impact, shown with
  "Assumes: …" (the condition it depends on) and a badge that TrustTable
  derives — *Conditional*, or *Informed by your confirmed context* when it
  cites context the user confirmed; there is deliberately no
  *Evidence-backed* badge, because the deterministic evidence establishes
  what was found in the data, not what it costs the business; the section
  says these are potential impacts, not established facts;
- remediation (`REM-01`) is one or more structured recommendations, each
  showing who should act, how urgently, how to correct already-affected
  rows, how to prevent recurrence at the source, an always-shown risk
  warning, how to verify the fix, and an optional technical example; it
  states it is advisory and that TrustTable never changes the user's
  data;
- the validation rule is badged *Proposed — not active* and states that
  TrustTable does not run or enforce it and nothing is activated
  automatically;
- an empty section shows an honest empty state, not a "not yet
  available" placeholder.

**Implemented (`UI-03` slice 4): review controls.** The section shows the
current persisted review (state and save time) and a form with the four
states (*Unreviewed*, *Confirmed*, *Needs investigation*, *Dismissed*), an
optional note, and a dismissal reason that appears and is required only
when *Dismissed* is chosen; saving is blocked until the reason is given.
Saving calls `PUT .../findings/{finding_id}/review` and the screen then
shows the state the server returned; a server rejection appears as an
inline alert. The section states that a review records the manager's
decision only and does not change the finding, its evidence or the data.
The findings list shows each finding's review state in a *Review* column.
**Not implemented:** filtering the list by review state (the list route has
no filters yet).

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

**Implemented (`UI-03` slice 3):** `/analyses/:analysisId/rules`, linked as
*Rules* from the analysis layout of a completed analysis. *Validation
rules* lists every stored rule with its business description, enabled
state, severity, provenance and the latest pass, fail and skipped counts
(or "Not run yet", or the reason the last run could not complete), with an
honest empty state. *Show details* expands a rule to its type, scope,
columns, null handling, the parameters its type uses, and the bounded
example failures of the latest run, all read-only. *Run rule* re-executes
the rule and refreshes the counts; *Delete rule* asks for confirmation in
an accessible dialog and removes the rule. *Download JSON* and *Download
YAML* save the served validated-rules export as a file (never inserted into
the page). Rule and failure text comes from the dataset and is only
rendered as escaped text. Failures show an inline error and the page stays
put. Still **not implemented**: editing supported parameters and toggling
the enabled state (the API has no update route), and the expandable
YAML/JSON view of a single rule.

### 4.10 Report

Show:

- report preview
- included sections
- generation status
- Markdown download
- JSON/YAML rule downloads

**Implemented (`UI-03` slice 2):** `/analyses/:analysisId/report`, linked as
*Report* from the analysis layout of a completed analysis. The screen
offers the three report options (*include dismissed findings*, *include
technical appendix*, *include bounded examples*), all **off** by default;
the bounded-examples option says examples may quote values from the
dataset. *Generate report* stores one immutable snapshot with exactly the
chosen options. *Generated reports* lists the stored snapshots in the order
served, each with its generation time, chosen options and content hash,
and an honest empty state. *Download Markdown* saves the stored Markdown of
that report as a file (never re-rendered). Report text is only saved, never
inserted into the page. Failures show an inline error and the page stays
put. The JSON/YAML rule downloads are on the Rules screen (slice 3). Still
**not implemented**: an in-page report preview, included-section listing
and generation-progress status (generation is a single request).

### 4.11 Technical details

Expandable technical information:

- profile metrics
- detector IDs and versions
- thresholds
- prompt and model metadata
- timings
- sampled/full-data labels

**Current behavior (`UI-03` slice 5).** The Technical link opens a read-only
page for a completed analysis, built only from existing routes: dataset and
analysis facts (format, size, content hash, timestamps) and the AI exposure
posture; the profile with schema version, a sampled or full-data label,
profiling timing, dataset metrics, warnings, and per-column type, empty and
distinct counts with collapsed, expandable metrics; and the detectors that
produced findings with their versions, finding counts and confidence range
(derived from the findings list). Dataset-derived text is rendered as plain
text. Still **not implemented**, because no route exposes them: detector
thresholds and analysis-level prompt and model metadata; the page says so.
Detectors that found nothing are not listed.

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

## 12. Planned redesign — target behavior (planned, not built)

> **Status.** Sections 1 to 11 describe the interface as it is built. This section
> records the owner-confirmed target of the UI/UX redesign (`UX-01`,
> `docs/decision-log.md` D-066, D-067). **Slice S1 (`UX-02`, D-068) is built: the
> Workspace, the Configure step, the Run of the staged bytes, the Local AI and privacy
> status and the disabled Compare area (sections 4.1 and 4.2). Nothing else in this
> section is built, and nothing here may be presented in the interface as available
> until its slice ships.**
> Proposal-level designs are marked as such and are to be confirmed in each slice's
> specification, which needs a fresh, substantive independent review before
> implementation.

### 12.1 Principles

- Business language first, technical detail second; technical detail through
  progressive disclosure and an Advanced mode.
- The scored result is called a **Finding**; neutral pattern results are
  **Observations** ("Worth knowing"). Findings are not described as faults or alarms;
  severity, category, evidence and guidance explain seriousness.
- Every provenance is shown in business wording and distinguished: deterministic
  analysis, built-in guidance, user-confirmed context, and local AI interpretation.
- No capability that does not exist is shown as active. A planned capability may be
  shown only as disabled with a statement that it is planned.
- Raw internal values (category and severity identifiers), content hashes and
  similar identifiers do not appear in the normal interface; they appear only in
  Advanced or diagnostic views where technically useful.

### 12.2 Workflow and navigation (confirmed)

Choose data, Configure, Run, Review, Act and Export. Choosing a file never starts an
analysis.

- **Workspace (landing page):** upload of a CSV or XLSX file, the sales demo, recent
  analyses with reopen, rerun and delete, a notice when a chosen file exactly matches
  a previously analysed file, and a visible but disabled *Compare datasets* area that
  states comparison is planned and not implemented.
- **Configure:** file facts, worksheet choice where relevant, known readability
  problems (including an unsupported encoding) reported before Run, a short grouped
  business-language summary of what TrustTable will check (no detector names; more
  detail by progressive disclosure), Local AI status noting that AI assistance is
  optional and separate, a privacy statement, and one *Run analysis* action. There are
  no category or detector on/off controls: the standard analysis always runs and the
  trust assessment means that it ran.
- **Review:** Overview, Findings (with previous, next and next-unreviewed navigation
  and review-state filtering), the finding-scoped inspector, Observations, and About
  this data (context). There is **no separate Data tab**.
- **Act and Export:** Reports and the Rules hand-off area (12.7). Technical details
  are shown in Advanced mode.
- Persistent workspace navigation: Home, Analyses, Compare (disabled), Settings
  (Normal and Advanced), Help. Existing routes remain reachable.

### 12.3 Analysis progress

Stages in business wording for the deterministic analysis. "Results ready" means the
deterministic result is ready. Optional AI work is shown separately, per finding, and
never blocks or delays the deterministic result. No time estimate is shown unless
measured.

### 12.4 Findings review and the data inspector (confirmed boundaries)

The inspector is **finding-scoped**: it is reached from a finding, or from an
observation that carries example rows. It offers scrolling in both directions, sticky
headers, highlighted affected cells and columns, previous and next affected row, and a
return-to-the-issue control. For a column-wide finding it prefers existing, safe
evidence or example-row anchors and otherwise a deterministic bounded window such as
the head of the dataset; there is no arbitrary sampling and no general dataset browser.
Navigation never implies that every affected row can be visited unless the complete set
is retained, and says so honestly when only a bounded subset exists. Cell values are
rendered as inert text, and suspicious values stay truncated until the user chooses to
reveal them (section 8). Window sizes and paging limits are set only after a parse and
caching performance measurement on the real product path. Making row data visible does
not by itself expand what is sent to AI, promote row context into canonical finding
evidence, or add row data to reports or exports; existing, explicitly requested,
bounded report and evidence examples keep their existing contracts.

### 12.5 AI enrichment

On demand, persisted and non-blocking per finding. Deterministic content, evidence and
built-in guidance render immediately. The AI area has its own state: preparing, ready,
unavailable or failed, and marks a result stale when the finding, the confirmed
context, the model or the prompt contract it was bound to has changed. There are no
automatic explanations for every finding.

### 12.6 Settings

Normal settings each state what they control, why a normal user might change them and
the consequences. Technical and AI implementation detail (provider, runtime location,
model identity, timeouts) is only in Advanced. A setting managed by the installation
is shown read-only with its effective value and a plain explanation; the product never
edits deployment configuration. Display preferences are browser-local. No auto-delete
setting is offered.

### 12.7 Rules (secondary hand-off area)

Placed under Act and Export. States that these are executable validation rules for the
current analysis, that they can be validated and exported for the team responsible for
the data source or pipeline, and that TrustTable does not currently apply them
automatically to later files or other datasets. Listing, running, deleting and export
remain. There is no creation from Findings and no manual authoring or editing. The
terms "Rules", "Checks" and "Expectations" are not settled for a future persistent
capability (`RULE-04`).

### 12.8 Local AI

The normal interface shows whether AI assistance is enabled, whether the local runtime
is ready, which model is active, that processing stays local, what AI adds and what
works without it. The first stage (`UX-09`) is honest status, guided setup,
compatibility and readiness checks and connection testing; it performs no download or
installation. Product-managed setup of a small curated range of hardware-appropriate
profiles is the approved goal, but its mechanism is not approved (`LAI-01`). Profiles
are capability tiers, not hardware requirements. No hardware, performance, quality or
memory claim is shown without qualification evidence. There is no unrestricted
model-repository browsing; downloads, storage, licences and network egress always need
explicit consent.

### 12.9 Proposal-level designs (not yet confirmed)

Dashboard metrics and visualizations, progress stage wording, the provenance and help
model, the empty, loading and error pattern, the contents of Normal and Advanced,
and curated profile names are proposals, to be confirmed in the slice specifications.
