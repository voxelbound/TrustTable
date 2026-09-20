import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type {
  BusinessImpactStatementResponse,
  ProposedValidationRuleResponse,
} from '../../api'
import {
  BusinessImpactSection,
  RemediationSection,
  ValidationRuleSection,
} from './FindingGuidanceSections'

// The reviewer's exact counterexample: free-text consequences the deterministic
// evidence does not establish. Whatever the model wrote, TrustTable derived a
// conditional basis for it, and the UI has no "Evidence-backed" badge to give.
const INVENTED: BusinessImpactStatementResponse = {
  statement:
    'This will cause the company to lose money and damage its reputation.',
  basis: 'assumption',
  evidence_ids: ['ev-1'],
  context_fields: [],
  assumption: 'the flagged rows are used in reports',
}
const CONTEXT: BusinessImpactStatementResponse = {
  statement: 'Each order should appear on one row.',
  basis: 'confirmed_context',
  evidence_ids: [],
  context_fields: ['row_grain', 'primary_entity'],
  assumption: 'orders are counted per row',
}
const ASSUMPTION: BusinessImpactStatementResponse = {
  statement: 'Order counts may be overstated.',
  basis: 'assumption',
  evidence_ids: [],
  context_fields: [],
  assumption: 'the rows feed order-count reporting',
}

const RULE: ProposedValidationRuleResponse = {
  rule_type: 'unique',
  columns: [
    { original_name: 'Order ID', internal_key: 'order_id', ordinal: 0 },
    { original_name: 'Line', internal_key: 'line', ordinal: 1 },
  ],
  description: 'Each row should be unique across the order columns.',
  status: 'proposed',
}

describe('BusinessImpactSection', () => {
  it('labels each statement conditional or context-informed and always shows its condition', () => {
    render(
      <BusinessImpactSection
        statements={[CONTEXT, ASSUMPTION]}
        aiAssisted={true}
      />,
    )

    expect(
      screen.getByRole('heading', { name: 'Possible business impact' }),
    ).toBeInTheDocument()
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(
      within(items[0]!).getByText('Informed by your confirmed context'),
    ).toBeInTheDocument()
    expect(
      within(items[0]!).getByText(
        'Draws on your confirmed row grain, primary entity',
      ),
    ).toBeInTheDocument()
    expect(
      within(items[0]!).getByText('Assumes: orders are counted per row'),
    ).toBeInTheDocument()
    expect(within(items[1]!).getByText('Conditional')).toBeInTheDocument()
    expect(
      within(items[1]!).getByText(
        'Assumes: the rows feed order-count reporting',
      ),
    ).toBeInTheDocument()
  })

  it('never presents an invented business consequence as evidence-backed', () => {
    render(<BusinessImpactSection statements={[INVENTED]} aiAssisted={true} />)

    const item = screen.getByRole('listitem')
    expect(
      within(item).getByText(/lose money and damage its reputation/),
    ).toBeInTheDocument()
    // Presented as conditional, with its condition, under a section that says
    // these are potential impacts and not established facts.
    expect(within(item).getByText('Conditional')).toBeInTheDocument()
    expect(
      within(item).getByText('Assumes: the flagged rows are used in reports'),
    ).toBeInTheDocument()
    expect(screen.getByText(/not established facts/)).toBeInTheDocument()
    expect(screen.queryByText(/Evidence-backed/i)).toBeNull()
    expect(screen.queryByText(/From your confirmed context/i)).toBeNull()
  })

  it('says whether the section is AI-assisted or built-in guidance', () => {
    const { rerender } = render(
      <BusinessImpactSection statements={[ASSUMPTION]} aiAssisted={true} />,
    )
    expect(screen.getByText(/^AI-assisted\./)).toBeInTheDocument()
    rerender(
      <BusinessImpactSection statements={[ASSUMPTION]} aiAssisted={false} />,
    )
    expect(
      screen.getByText(/^Built-in guidance\. These are potential impacts/),
    ).toBeInTheDocument()
  })

  it('shows an honest empty state rather than a placeholder', () => {
    render(<BusinessImpactSection statements={[]} aiAssisted={false} />)
    expect(
      screen.getByText(
        'No business-impact statements were produced for this finding.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Not yet available/)).toBeNull()
  })

  it('renders model text as plain text, never as markup', () => {
    render(
      <BusinessImpactSection
        statements={[
          { ...ASSUMPTION, statement: '<img src=x onerror=alert(1)> risk' },
        ]}
        aiAssisted={true}
      />,
    )
    expect(screen.getByText(/<img src=x onerror=alert\(1\)> risk/)).toBeTruthy()
    expect(document.querySelector('img')).toBeNull()
  })
})

describe('RemediationSection', () => {
  it('lists steps in order and states that the advice is advisory only', () => {
    render(
      <RemediationSection
        steps={['Check the duplicates.', 'Remove true duplicates at source.']}
        aiAssisted={false}
      />,
    )
    expect(
      screen.getByRole('heading', { name: 'Remediation' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/never changes your uploaded data/),
    ).toBeInTheDocument()
    const steps = screen.getAllByRole('listitem')
    expect(steps.map((li) => li.textContent)).toEqual([
      'Check the duplicates.',
      'Remove true duplicates at source.',
    ])
  })

  it('notes AI assistance when an AI interpretation produced the steps', () => {
    render(<RemediationSection steps={['Do x.']} aiAssisted={true} />)
    expect(screen.getByText(/These suggestions were AI-assisted/)).toBeTruthy()
  })

  it('shows an honest empty state', () => {
    render(<RemediationSection steps={[]} aiAssisted={false} />)
    expect(
      screen.getByText('No remediation steps were produced for this finding.'),
    ).toBeInTheDocument()
  })
})

describe('ValidationRuleSection', () => {
  it('presents the rule as a proposal that is explicitly not active', () => {
    render(<ValidationRuleSection rule={RULE} aiAssisted={false} />)

    expect(
      screen.getByRole('heading', { name: 'Validation rule' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Proposed — not active')).toBeInTheDocument()
    expect(screen.getByText('Unique')).toBeInTheDocument()
    expect(
      screen.getByText('Each row should be unique across the order columns.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Applies to: Order ID, Line')).toBeInTheDocument()
    expect(screen.getByText(/does not run or enforce it/)).toBeInTheDocument()
    expect(screen.getByText(/nothing is activated automatically/)).toBeTruthy()
    // Nothing on the section says the rule is on.
    expect(screen.queryByText(/^Active$/)).toBeNull()
    expect(screen.queryByText(/enabled/i)).toBeNull()
  })

  it('falls back to a humanized label for an unknown rule type', () => {
    render(
      <ValidationRuleSection
        rule={{ ...RULE, rule_type: 'some_new_type', columns: [] }}
        aiAssisted={true}
      />,
    )
    expect(screen.getByText('some new type')).toBeInTheDocument()
    expect(screen.queryByText(/Applies to/)).toBeNull()
    expect(screen.getByText(/The proposal was AI-assisted/)).toBeTruthy()
  })

  it('shows an honest empty state when no rule was proposed', () => {
    render(<ValidationRuleSection rule={null} aiAssisted={false} />)
    expect(
      screen.getByText('No validation rule was proposed for this finding.'),
    ).toBeInTheDocument()
  })
})
