import { describe, expect, it } from 'vitest'
import {
  countBySeverity,
  filterFindings,
  REVIEW_STATES,
  reviewStateLabel,
  severityLabel,
  severityRank,
  sortFindingsByPriority,
  type FindingRecord,
} from './finding'

describe('severityLabel', () => {
  it('names every known severity in business wording', () => {
    expect(
      ['critical', 'high', 'medium', 'low', 'informational'].map(severityLabel),
    ).toEqual(['Critical', 'High', 'Medium', 'Low', 'Informational'])
  })

  it('returns an unknown severity unchanged instead of hiding it', () => {
    expect(severityLabel('brand_new')).toBe('brand_new')
  })
})

describe('filterFindings by review state', () => {
  const findings = [
    {
      detector_id: 'd',
      detector_version: '1',
      category: 'validity',
      severity: 'low',
      confidence: 1,
      priority_score: 1,
      calculated_observation: 'one',
      affected_columns: [],
      affected_row_count: 1,
      evidence_count: 1,
      review_state: 'unreviewed',
    },
    {
      detector_id: 'd',
      detector_version: '1',
      category: 'validity',
      severity: 'low',
      confidence: 1,
      priority_score: 1,
      calculated_observation: 'two',
      affected_columns: [],
      affected_row_count: 1,
      evidence_count: 1,
      review_state: 'dismissed',
    },
  ]

  it('keeps only findings in the requested review state', () => {
    expect(
      filterFindings(findings, { reviewState: 'dismissed' }).map(
        (finding) => finding.calculated_observation,
      ),
    ).toEqual(['two'])
  })

  it('applies no review filter when none is given', () => {
    expect(filterFindings(findings, {})).toHaveLength(2)
  })

  it('combines with the other filters', () => {
    expect(
      filterFindings(findings, { reviewState: 'dismissed', severity: 'high' }),
    ).toEqual([])
  })
})

function makeFinding(overrides: Partial<FindingRecord> = {}): FindingRecord {
  return {
    detector_id: 'structural.exact_duplicate_rows',
    detector_version: '1.0.0',
    category: 'structural',
    severity: 'medium',
    confidence: 0.8,
    priority_score: 50,
    calculated_observation: 'Two rows are exact duplicates.',
    affected_columns: [],
    affected_row_count: 2,
    evidence_count: 1,
    ...overrides,
  }
}

describe('severityRank', () => {
  it('orders known severities from critical (most severe) to informational', () => {
    expect(severityRank('critical')).toBeLessThan(severityRank('high'))
    expect(severityRank('high')).toBeLessThan(severityRank('medium'))
    expect(severityRank('medium')).toBeLessThan(severityRank('low'))
    expect(severityRank('low')).toBeLessThan(severityRank('informational'))
  })

  it('sorts an unknown severity value after every known severity', () => {
    expect(severityRank('unknown-value')).toBeGreaterThan(
      severityRank('informational'),
    )
  })
})

describe('sortFindingsByPriority', () => {
  it('sorts by priority_score descending', () => {
    const findings = [
      makeFinding({ detector_id: 'a', priority_score: 10 }),
      makeFinding({ detector_id: 'b', priority_score: 90 }),
      makeFinding({ detector_id: 'c', priority_score: 50 }),
    ]

    const sorted = sortFindingsByPriority(findings)

    expect(sorted.map((f) => f.detector_id)).toEqual(['b', 'c', 'a'])
  })

  it('does not mutate the input array', () => {
    const findings = [
      makeFinding({ detector_id: 'a', priority_score: 10 }),
      makeFinding({ detector_id: 'b', priority_score: 90 }),
    ]
    const originalOrder = findings.map((f) => f.detector_id)

    sortFindingsByPriority(findings)

    expect(findings.map((f) => f.detector_id)).toEqual(originalOrder)
  })

  it('returns an empty array for an empty input', () => {
    expect(sortFindingsByPriority([])).toEqual([])
  })
})

describe('filterFindings', () => {
  const findings = [
    makeFinding({
      detector_id: 'a',
      severity: 'critical',
      category: 'validity',
      calculated_observation: 'Future dates found in order_date.',
      affected_columns: [
        { original_name: 'order_date', internal_key: 'order_date', ordinal: 0 },
      ],
    }),
    makeFinding({
      detector_id: 'b',
      severity: 'low',
      category: 'consistency',
      calculated_observation: 'Inconsistent capitalization in category.',
      affected_columns: [
        { original_name: 'category', internal_key: 'category', ordinal: 1 },
      ],
    }),
  ]

  it('returns every finding when no filter is applied', () => {
    expect(filterFindings(findings, {})).toHaveLength(2)
  })

  it('filters by exact severity', () => {
    const result = filterFindings(findings, { severity: 'critical' })
    expect(result.map((f) => f.detector_id)).toEqual(['a'])
  })

  it('filters by exact category', () => {
    const result = filterFindings(findings, { category: 'consistency' })
    expect(result.map((f) => f.detector_id)).toEqual(['b'])
  })

  it('filters by case-insensitive search over the observation text', () => {
    const result = filterFindings(findings, { search: 'FUTURE DATES' })
    expect(result.map((f) => f.detector_id)).toEqual(['a'])
  })

  it('filters by case-insensitive search over affected column names', () => {
    const result = filterFindings(findings, { search: 'category' })
    expect(result.map((f) => f.detector_id)).toEqual(['b'])
  })

  it('combines severity, category, and search filters (AND semantics)', () => {
    const result = filterFindings(findings, {
      severity: 'critical',
      category: 'validity',
      search: 'order_date',
    })
    expect(result.map((f) => f.detector_id)).toEqual(['a'])
  })

  it('returns an empty array when no finding matches', () => {
    expect(filterFindings(findings, { severity: 'informational' })).toEqual([])
  })

  it('ignores a blank/whitespace-only search term', () => {
    expect(filterFindings(findings, { search: '   ' })).toHaveLength(2)
  })
})

describe('countBySeverity', () => {
  it('counts findings per severity, omitting severities with zero findings', () => {
    const findings = [
      makeFinding({ severity: 'high' }),
      makeFinding({ severity: 'high' }),
      makeFinding({ severity: 'low' }),
    ]

    expect(countBySeverity(findings)).toEqual({ high: 2, low: 1 })
  })

  it('returns an empty object for an empty input', () => {
    expect(countBySeverity([])).toEqual({})
  })
})

describe('reviewStateLabel', () => {
  it('labels every selectable review state', () => {
    expect(REVIEW_STATES.map(reviewStateLabel)).toEqual([
      'Unreviewed',
      'Confirmed',
      'Needs investigation',
      'Dismissed',
    ])
  })

  it('returns an unrecognized state unchanged rather than hiding it', () => {
    expect(reviewStateLabel('archived')).toBe('archived')
  })
})
