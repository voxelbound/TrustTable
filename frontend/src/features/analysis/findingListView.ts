import {
  filterFindings,
  sortFindingsByPriority,
  type FindingFilter,
  type FindingRecord,
} from '../../domain/finding'

/** The Findings screen's filters, owned by URL search parameters
 * (`docs/ui-specification.md` §6). The finding detail screen reads the same
 * parameters so previous, next and next-unreviewed follow exactly the list
 * the reviewer was looking at. */
export function findingFilterFromSearch(
  searchParams: URLSearchParams,
): FindingFilter {
  return {
    severity: searchParams.get('severity') || undefined,
    category: searchParams.get('category') || undefined,
    reviewState: searchParams.get('review') || undefined,
    search: searchParams.get('search') || undefined,
  }
}

/** The filtered findings in priority order: what the Findings screen shows
 * and what navigation steps through. */
export function visibleFindings<T extends FindingRecord>(
  findings: readonly T[],
  filter: FindingFilter,
): T[] {
  return sortFindingsByPriority(filterFindings(findings, filter))
}

/** The search string to carry from the list to a finding and back, so the
 * active filters survive navigation. Empty when no filter is active. */
export function carriedSearch(searchParams: URLSearchParams): string {
  const text = searchParams.toString()
  return text ? `?${text}` : ''
}
