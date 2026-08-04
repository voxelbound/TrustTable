# Engineering Review 004: User Interface Baseline

**Status:** Accepted

## User experience direction

TrustTable is a structured investigation workspace, not a chatbot.

## Required hierarchy

1. trust assessment
2. top concerns
3. immediate actions
4. remaining findings
5. dataset summary
6. technical details

## Required provenance labels

- Calculated
- AI interpretation
- Confirmed by user
- Corrected by user
- Deterministic fallback

## Security presentation

Prompt-injection findings receive dedicated UI showing:

- affected field
- escaped truncated sample
- sent-to-model status
- model location
- protections
- output rejection state

## Accessibility

- keyboard-operable workflow
- visible focus
- live progress announcements
- text severity
- no color-only meaning
- automated and manual release checks

## Outcome

UI architecture approved for implementation after repository foundation.
