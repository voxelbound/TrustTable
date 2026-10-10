import { describe, expect, it } from 'vitest'
import { navigateFindings } from './findingNavigation'

const LIST = [
  { finding_id: 'a', review_state: 'confirmed' },
  { finding_id: 'b', review_state: 'unreviewed' },
  { finding_id: 'c', review_state: 'dismissed' },
  { finding_id: 'd', review_state: 'unreviewed' },
]

describe('navigateFindings', () => {
  it('reports the one-based position and the neighbours in list order', () => {
    expect(navigateFindings(LIST, 'b')).toMatchObject({
      position: 2,
      total: 4,
      previousId: 'a',
      nextId: 'c',
    })
  })

  it('has no previous at the start and no next at the end, and never wraps', () => {
    expect(navigateFindings(LIST, 'a').previousId).toBeNull()
    expect(navigateFindings(LIST, 'd').nextId).toBeNull()
  })

  it('next-unreviewed skips reviewed findings and follows list order', () => {
    expect(navigateFindings(LIST, 'a').nextUnreviewedId).toBe('b')
    expect(navigateFindings(LIST, 'b').nextUnreviewedId).toBe('d')
  })

  it('next-unreviewed does not wrap back to an earlier unreviewed finding', () => {
    expect(navigateFindings(LIST, 'd').nextUnreviewedId).toBeNull()
  })

  it('never offers the current finding as its own next-unreviewed', () => {
    const only = [{ finding_id: 'x', review_state: 'unreviewed' }]
    expect(navigateFindings(only, 'x').nextUnreviewedId).toBeNull()
  })

  it('treats only the unreviewed state as unreviewed', () => {
    const list = [
      { finding_id: 'a', review_state: 'needs_investigation' },
      { finding_id: 'b', review_state: 'confirmed' },
      { finding_id: 'c' },
    ]
    expect(navigateFindings(list, 'a').nextUnreviewedId).toBeNull()
  })

  it('has no position or neighbours when the finding is not in the list, but offers the first unreviewed', () => {
    expect(navigateFindings(LIST, 'missing')).toEqual({
      position: null,
      total: 4,
      previousId: null,
      nextId: null,
      nextUnreviewedId: 'b',
    })
  })

  it('handles an empty list', () => {
    expect(navigateFindings([], 'a')).toEqual({
      position: null,
      total: 0,
      previousId: null,
      nextId: null,
      nextUnreviewedId: null,
    })
  })

  it('a single finding has no neighbours', () => {
    expect(
      navigateFindings([{ finding_id: 'a', review_state: 'confirmed' }], 'a'),
    ).toEqual({
      position: 1,
      total: 1,
      previousId: null,
      nextId: null,
      nextUnreviewedId: null,
    })
  })
})
