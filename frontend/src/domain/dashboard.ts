/**
 * Pure dashboard logic for the Overview (`UX-04`, D-070): distributions,
 * the columns with most findings, review progress and honest percentage
 * formatting.
 *
 * No React or API-client import (`docs/ui-specification.md` §5). Input
 * shapes are structural so this module stays decoupled from the generated
 * client, like `domain/finding.ts`.
 */

import { severityRank } from './finding'

/** Business-language names for the closed `DetectorCategory` set
 * (`detectors/contract.py`). An unknown value is shown unchanged rather
 * than hidden, so a new category is never silently dropped. */
const CATEGORY_LABELS: Record<string, string> = {
  structural: 'File structure',
  completeness: 'Missing values',
  consistency: 'Consistency',
  validity: 'Valid values',
  statistical: 'Unusual values',
  cross_field: 'Relationships between columns',
  ai_processing_security: 'Content safety',
}

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category
}

export interface DistributionEntry {
  key: string
  count: number
}

/** Counts per value, ordered by `order` (known values first, in that
 * order) and then by count descending and key. Zero-count values are
 * omitted. */
function distribution<T>(
  items: readonly T[],
  keyOf: (item: T) => string,
  compare: (a: DistributionEntry, b: DistributionEntry) => number,
): DistributionEntry[] {
  const counts = new Map<string, number>()
  for (const item of items) {
    const key = keyOf(item)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([key, count]) => ({ key, count }))
    .sort(compare)
}

/** Severity distribution, most severe first. */
export function severityDistribution(
  findings: readonly { severity: string }[],
): DistributionEntry[] {
  return distribution(
    findings,
    (finding) => finding.severity,
    (a, b) =>
      severityRank(a.key) - severityRank(b.key) || a.key.localeCompare(b.key),
  )
}

/** Category distribution, largest first. */
export function categoryDistribution(
  findings: readonly { category: string }[],
): DistributionEntry[] {
  return distribution(
    findings,
    (finding) => finding.category,
    (a, b) => b.count - a.count || a.key.localeCompare(b.key),
  )
}

export interface ColumnFindingCount {
  name: string
  count: number
}

/** The columns named by the most findings. A finding that names several
 * columns counts once for each of them; a finding that names none (a
 * whole-file finding) contributes to no column. Ties break by name so the
 * order is deterministic. */
export function columnsWithMostFindings(
  findings: readonly {
    affected_columns: readonly { original_name: string }[]
  }[],
  limit = 5,
): ColumnFindingCount[] {
  const counts = new Map<string, number>()
  for (const finding of findings) {
    const seen = new Set(finding.affected_columns.map((c) => c.original_name))
    for (const name of seen) {
      counts.set(name, (counts.get(name) ?? 0) + 1)
    }
  }
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
    .slice(0, limit)
}

export interface ReviewProgress {
  total: number
  /** Findings with any state other than `unreviewed`. */
  reviewed: number
  byState: DistributionEntry[]
}

/** How much of the findings list a person has looked at. A review is a
 * manager's decision only; it never changes a finding. */
export function reviewProgress(
  findings: readonly { review_state: string }[],
): ReviewProgress {
  const byState = distribution(
    findings,
    (finding) => finding.review_state,
    (a, b) => b.count - a.count || a.key.localeCompare(b.key),
  )
  const unreviewed =
    byState.find((entry) => entry.key === 'unreviewed')?.count ?? 0
  return {
    total: findings.length,
    reviewed: findings.length - unreviewed,
    byState,
  }
}

/** A percentage that never rounds a real, non-zero share down to "0%" or a
 * real, non-complete share up to "100%". `null` means nothing to measure. */
export function formatShare(share: number | null): string {
  if (share === null) {
    return 'not measured'
  }
  if (share <= 0) {
    return '0%'
  }
  if (share >= 1) {
    return '100%'
  }
  const percent = share * 100
  if (percent < 0.1) {
    return 'less than 0.1%'
  }
  if (percent > 99.9) {
    return 'more than 99.9%'
  }
  return `${percent.toFixed(1).replace(/\.0$/, '')}%`
}
