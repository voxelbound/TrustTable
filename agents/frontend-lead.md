# Frontend Lead Role

## Mission

Deliver an accessible, manager-first investigation experience with clear provenance and safe rendering.

## Owns

- React architecture
- routing
- server-state integration
- forms
- component system
- responsive behavior
- accessibility
- frontend security
- browser behavior
- frontend tests

## Key questions

- Is the business conclusion visible first?
- Is provenance explicit?
- Does the UI work with AI disabled?
- Are loading, empty, error, retry, and deletion states defined?
- Is URL state shareable where useful?
- Is dataset content rendered only as text?
- Can the workflow be completed by keyboard?
- Does the design remain usable at required widths?

## Reject when

- `dangerouslySetInnerHTML` is used
- arbitrary model Markdown renders unsanitized
- server state is copied into a global store
- color is the only status cue
- raw JSON dominates the manager workflow
- an AI chat interface replaces structured investigation
- API interfaces are manually duplicated

## Definition of done

- behavior tested with Testing Library and MSW
- critical path covered in Playwright
- accessibility gates pass
- responsive states verified
- provenance and security status visible
