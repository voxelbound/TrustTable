import { describe, expect, it } from 'vitest'
import {
  affectedRowPosition,
  MAX_CELL_CHARACTERS,
  resolveAnchorRow,
  shownCell,
} from './inspector'

describe('shownCell', () => {
  it('shows a short value whole', () => {
    expect(shownCell('abc')).toEqual({
      text: 'abc',
      shortened: false,
      length: 3,
    })
  })

  it('shows a value of exactly the limit whole', () => {
    const value = 'x'.repeat(MAX_CELL_CHARACTERS)
    expect(shownCell(value).shortened).toBe(false)
  })

  it('shortens a longer value and reports its full length', () => {
    const value = 'y'.repeat(MAX_CELL_CHARACTERS + 50)
    const shown = shownCell(value)
    expect(shown.shortened).toBe(true)
    expect(shown.text).toHaveLength(MAX_CELL_CHARACTERS)
    expect(shown.length).toBe(MAX_CELL_CHARACTERS + 50)
  })

  it('never splits a character outside the basic plane', () => {
    const value = '😀'.repeat(10)
    const shown = shownCell(value, 4)
    expect(shown.text).toBe('😀😀😀😀')
    expect(shown.length).toBe(10)
  })

  it('does not call a value shortened when its code points fit', () => {
    const value = '😀'.repeat(4) // 8 UTF-16 units, 4 code points
    expect(shownCell(value, 4).shortened).toBe(false)
  })

  it('keeps markup and formula text as plain text', () => {
    expect(shownCell('<script>alert(1)</script>').text).toBe(
      '<script>alert(1)</script>',
    )
    expect(shownCell('=HYPERLINK("http://x","y")').text).toBe(
      '=HYPERLINK("http://x","y")',
    )
  })
})

describe('affectedRowPosition', () => {
  const rows = [4, 9, 17]

  it('reports position and neighbours', () => {
    expect(affectedRowPosition(rows, 9)).toEqual({
      position: 2,
      total: 3,
      previousRow: 4,
      nextRow: 17,
    })
  })

  it('has no previous at the first row and no next at the last, never wrapping', () => {
    expect(affectedRowPosition(rows, 4)?.previousRow).toBeNull()
    expect(affectedRowPosition(rows, 17)?.nextRow).toBeNull()
  })

  it('returns null for a row that is not one of the finding’s own', () => {
    expect(affectedRowPosition(rows, 5)).toBeNull()
  })
})

describe('resolveAnchorRow', () => {
  const rows = [4, 9, 17]

  it('uses the requested row when it belongs to the finding', () => {
    expect(resolveAnchorRow(rows, '9')).toBe(9)
  })

  it('falls back to the first affected row for anything else', () => {
    expect(resolveAnchorRow(rows, null)).toBe(4)
    expect(resolveAnchorRow(rows, '5')).toBe(4)
    expect(resolveAnchorRow(rows, '-1')).toBe(4)
    expect(resolveAnchorRow(rows, '9abc')).toBe(4)
    expect(resolveAnchorRow(rows, '')).toBe(4)
  })

  it('has no row when the finding has no affected rows', () => {
    expect(resolveAnchorRow([], '3')).toBeNull()
  })
})
