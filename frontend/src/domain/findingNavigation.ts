/**
 * Pure navigation over an already filtered and sorted list of findings
 * (`UX-05`, slice S4; `docs/ui-specification.md` §12.2).
 *
 * No React or API-client import (`docs/ui-specification.md` §5). The caller
 * passes the same list the Findings screen shows, so previous, next and
 * next-unreviewed always follow the active filters and priority order.
 * Navigation never wraps silently: past either end the target is `null` and
 * the caller says so.
 */

export interface NavigableFinding {
  finding_id: string
  review_state?: string
}

export interface FindingNavigation {
  /** One-based position of the current finding in the list, or `null` when
   * it is not in the list (for example, a filter now excludes it). */
  position: number | null
  total: number
  previousId: string | null
  nextId: string | null
  /** The first unreviewed finding after the current one; when the current
   * finding is not in the list, the first unreviewed finding in the list.
   * `null` when none remains: it never wraps back to the start. */
  nextUnreviewedId: string | null
}

const UNREVIEWED = 'unreviewed'

export function navigateFindings(
  list: readonly NavigableFinding[],
  currentId: string,
): FindingNavigation {
  const index = list.findIndex((finding) => finding.finding_id === currentId)
  const inList = index !== -1

  const nextUnreviewed = list.find(
    (finding, candidateIndex) =>
      candidateIndex > index &&
      finding.finding_id !== currentId &&
      finding.review_state === UNREVIEWED,
  )

  return {
    position: inList ? index + 1 : null,
    total: list.length,
    previousId: inList && index > 0 ? list[index - 1].finding_id : null,
    nextId:
      inList && index < list.length - 1 ? list[index + 1].finding_id : null,
    nextUnreviewedId: nextUnreviewed?.finding_id ?? null,
  }
}
