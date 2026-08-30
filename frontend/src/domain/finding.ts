/**
 * Pure finding-list logic (sorting/filtering/severity counting) shared by
 * the Overview and Findings screens (`UI-01`).
 *
 * No React or `frontend/src/api` import (`docs/ui-specification.md` §5's
 * dependency-direction rule: "domain -> no React or API-client
 * imports"). `FindingRecord` intentionally structurally duplicates the
 * fields of the generated `FindingItem` type it is used with at call
 * sites, rather than importing that type, so this module stays fully
 * decoupled from the API-client layer.
 */

export interface FindingColumnReference {
  original_name: string
  internal_key: string
  ordinal: number
}

export interface FindingRecord {
  detector_id: string
  detector_version: string
  category: string
  severity: string
  confidence: number
  priority_score: number
  calculated_observation: string
  affected_columns: FindingColumnReference[]
  affected_row_count: number
  evidence_count: number
}

/** `Severity` enum values (`domain/value_objects.py`), most-severe
 * first. A value outside this closed set sorts after every known
 * severity rather than throwing. */
const SEVERITY_ORDER: readonly string[] = [
  'critical',
  'high',
  'medium',
  'low',
  'informational',
]

export function severityRank(severity: string): number {
  const index = SEVERITY_ORDER.indexOf(severity)
  return index === -1 ? SEVERITY_ORDER.length : index
}

/** Returns a new array (does not mutate `findings`), ordered by
 * `priority_score` descending — the same ordering `docs/
 * ui-specification.md` §4.5 requires for the Overview screen's "top
 * three findings". */
export function sortFindingsByPriority<T extends { priority_score: number }>(
  findings: readonly T[],
): T[] {
  return [...findings].sort((a, b) => b.priority_score - a.priority_score)
}

export interface FindingFilter {
  severity?: string
  category?: string
  search?: string
}

/** Case-insensitive substring search over the observation text and
 * affected column names — the bounded, client-side interim behavior
 * disclosed in `WP-025`'s Recorded assumption 5 (the current `API-01`
 * surface takes no filter query parameters). */
export function filterFindings<T extends FindingRecord>(
  findings: readonly T[],
  filter: FindingFilter,
): T[] {
  const search = filter.search?.trim().toLowerCase()
  return findings.filter((finding) => {
    if (filter.severity && finding.severity !== filter.severity) {
      return false
    }
    if (filter.category && finding.category !== filter.category) {
      return false
    }
    if (search) {
      const haystack = [
        finding.calculated_observation,
        ...finding.affected_columns.map((column) => column.original_name),
      ]
        .join(' ')
        .toLowerCase()
      if (!haystack.includes(search)) {
        return false
      }
    }
    return true
  })
}

/** A count of findings per severity value actually present — omits
 * severities with zero findings rather than listing every possible
 * value at zero. */
export function countBySeverity<T extends { severity: string }>(
  findings: readonly T[],
): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const finding of findings) {
    counts[finding.severity] = (counts[finding.severity] ?? 0) + 1
  }
  return counts
}
