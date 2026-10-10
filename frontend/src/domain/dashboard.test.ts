import { describe, expect, it } from 'vitest'
import {
  categoryDistribution,
  categoryLabel,
  columnsWithMostFindings,
  formatShare,
  reviewProgress,
  severityDistribution,
} from './dashboard'

const col = (original_name: string) => ({ original_name })

describe('severityDistribution', () => {
  it('orders most severe first and omits zero counts', () => {
    const result = severityDistribution([
      { severity: 'low' },
      { severity: 'critical' },
      { severity: 'low' },
      { severity: 'medium' },
    ])
    expect(result).toEqual([
      { key: 'critical', count: 1 },
      { key: 'medium', count: 1 },
      { key: 'low', count: 2 },
    ])
  })

  it('keeps an unknown severity after every known one instead of dropping it', () => {
    const result = severityDistribution([
      { severity: 'mystery' },
      { severity: 'informational' },
    ])
    expect(result.map((entry) => entry.key)).toEqual([
      'informational',
      'mystery',
    ])
  })
})

describe('categoryDistribution', () => {
  it('orders largest first, ties by key', () => {
    const result = categoryDistribution([
      { category: 'validity' },
      { category: 'completeness' },
      { category: 'validity' },
      { category: 'consistency' },
    ])
    expect(result.map((entry) => entry.key)).toEqual([
      'validity',
      'completeness',
      'consistency',
    ])
  })
})

describe('categoryLabel', () => {
  it('uses business wording and never a raw internal value for known categories', () => {
    for (const raw of [
      'structural',
      'completeness',
      'consistency',
      'validity',
      'statistical',
      'cross_field',
      'ai_processing_security',
    ]) {
      expect(categoryLabel(raw)).not.toBe(raw)
      expect(categoryLabel(raw)).not.toContain('_')
    }
  })

  it('shows an unknown category unchanged rather than hiding it', () => {
    expect(categoryLabel('brand_new')).toBe('brand_new')
  })
})

describe('columnsWithMostFindings', () => {
  it('counts a finding once per column it names, and none for a whole-file finding', () => {
    const result = columnsWithMostFindings([
      { affected_columns: [col('a'), col('b')] },
      { affected_columns: [col('a')] },
      { affected_columns: [] },
    ])
    expect(result).toEqual([
      { name: 'a', count: 2 },
      { name: 'b', count: 1 },
    ])
  })

  it('counts a column once even if one finding repeats it', () => {
    expect(
      columnsWithMostFindings([{ affected_columns: [col('a'), col('a')] }]),
    ).toEqual([{ name: 'a', count: 1 }])
  })

  it('is bounded and breaks ties by name deterministically', () => {
    const findings = ['d', 'c', 'b', 'a', 'f', 'e', 'g'].map((name) => ({
      affected_columns: [col(name)],
    }))
    const result = columnsWithMostFindings(findings, 3)
    expect(result.map((entry) => entry.name)).toEqual(['a', 'b', 'c'])
  })

  it('returns nothing when no finding names a column', () => {
    expect(columnsWithMostFindings([{ affected_columns: [] }])).toEqual([])
  })
})

describe('reviewProgress', () => {
  it('counts every state other than unreviewed as reviewed', () => {
    const progress = reviewProgress([
      { review_state: 'unreviewed' },
      { review_state: 'confirmed' },
      { review_state: 'dismissed' },
      { review_state: 'needs_investigation' },
    ])
    expect(progress.total).toBe(4)
    expect(progress.reviewed).toBe(3)
  })

  it('handles an empty list', () => {
    expect(reviewProgress([])).toEqual({ total: 0, reviewed: 0, byState: [] })
  })
})

describe('formatShare', () => {
  it('reports null as not measured, not as zero', () => {
    expect(formatShare(null)).toBe('not measured')
  })

  it('never rounds a real non-zero share down to 0%', () => {
    expect(formatShare(0.0001)).toBe('less than 0.1%')
    expect(formatShare(0)).toBe('0%')
  })

  it('never rounds a real non-complete share up to 100%', () => {
    expect(formatShare(0.9999)).toBe('more than 99.9%')
    expect(formatShare(1)).toBe('100%')
  })

  it('formats ordinary shares compactly', () => {
    expect(formatShare(0.5)).toBe('50%')
    expect(formatShare(0.123)).toBe('12.3%')
  })
})
