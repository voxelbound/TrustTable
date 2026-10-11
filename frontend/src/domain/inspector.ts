/**
 * Pure helpers for the finding-scoped data inspector (`UX-06`, slice S5;
 * `docs/ui-specification.md` §12.4, D-073).
 *
 * No React or API-client import (`docs/ui-specification.md` §5). Cell values
 * are untrusted text from the user's file: nothing here interprets them, and
 * the screen renders every value as a React text node, never as markup.
 */

/** Cell text longer than this stays shortened until the user reveals it. The
 * server returns values as stored; shortening is a display behavior. */
export const MAX_CELL_CHARACTERS = 120

export interface ShownCell {
  /** The text to show: the whole value, or its beginning when shortened. */
  text: string
  /** True when `text` is shorter than the value. */
  shortened: boolean
  /** Characters of the value, for the reveal control's label. */
  length: number
}

/** The part of a cell value to show before it is revealed. Counts and cuts by
 * code point, so a character outside the basic plane is never split. */
export function shownCell(
  value: string,
  limit: number = MAX_CELL_CHARACTERS,
): ShownCell {
  // A string of `limit` or fewer UTF-16 units cannot exceed `limit` code points.
  if (value.length <= limit) {
    return { text: value, shortened: false, length: value.length }
  }
  const points = Array.from(value)
  if (points.length <= limit) {
    return { text: value, shortened: false, length: points.length }
  }
  return {
    text: points.slice(0, limit).join(''),
    shortened: true,
    length: points.length,
  }
}

export interface AffectedRowPosition {
  /** One-based position of the current row among the finding's affected rows. */
  position: number
  total: number
  previousRow: number | null
  nextRow: number | null
}

/** Where `row` sits among the finding's own affected rows (ascending), or
 * `null` when it is not one of them. It never wraps: past either end the
 * target is `null` and the screen says so. */
export function affectedRowPosition(
  affectedRows: readonly number[],
  row: number,
): AffectedRowPosition | null {
  const index = affectedRows.indexOf(row)
  if (index === -1) {
    return null
  }
  return {
    position: index + 1,
    total: affectedRows.length,
    previousRow: index > 0 ? affectedRows[index - 1] : null,
    nextRow: index < affectedRows.length - 1 ? affectedRows[index + 1] : null,
  }
}

/** The affected row to show: the requested one when it belongs to the finding,
 * otherwise the first affected row. A row that is not the finding's own is
 * never requested from the server. `null` when the finding has none. */
export function resolveAnchorRow(
  affectedRows: readonly number[],
  requested: string | null,
): number | null {
  if (affectedRows.length === 0) {
    return null
  }
  if (requested !== null && /^\d+$/.test(requested)) {
    const row = Number(requested)
    if (affectedRows.includes(row)) {
      return row
    }
  }
  return affectedRows[0]
}
