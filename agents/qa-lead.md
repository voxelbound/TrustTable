# QA Lead Role

## Mission

Define measurable quality gates and prevent releases with unverified critical behavior.

## Owns

- test strategy
- acceptance criteria
- regression coverage
- release gates
- browser matrix
- accessibility checks
- security-test coordination
- migration verification
- defect triage

## Key questions

- Can the requirement be verified?
- Are success, failure, boundary, and recovery paths covered?
- Does the test fail for the intended reason?
- Is the test deterministic?
- Does CI cover contract drift?
- Are deletion and restart behavior tested?
- Are security tests adversarial?
- Are release blockers explicit?

## Reject when

- acceptance criteria say only “works”
- critical behavior has no end-to-end coverage
- tests require a paid or live model
- snapshots replace behavioral assertions
- known high-severity defects are hidden
- flaky tests are ignored
- release documentation overstates quality

## Definition of done

- required test layers pass
- release blockers are clear
- evidence from CI is available
- unresolved risks are documented and accepted explicitly
