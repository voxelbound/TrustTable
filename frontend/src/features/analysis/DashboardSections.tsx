import type { ReactNode } from 'react'
import { FindingSeverityBadge } from '../../components/provenance/FindingSeverityBadge'
import {
  categoryDistribution,
  categoryLabel,
  columnsWithMostFindings,
  formatShare,
  reviewProgress,
  severityDistribution,
  type DistributionEntry,
} from '../../domain/dashboard'
import { reviewStateLabel } from '../../domain/finding'
import type { AnalysisSummaryResponse, FindingItem } from '../../api'

const HEADING_CLASS = 'text-xl font-semibold text-slate-900 dark:text-slate-100'
const MUTED_CLASS = 'text-sm text-slate-600 dark:text-slate-400'

/** One labelled horizontal bar. The number is always printed, so the bar is
 * a visual aid only and carries no meaning that the text does not. */
function BarRow({
  label,
  count,
  max,
}: {
  label: ReactNode
  count: number
  max: number
}) {
  const width = max > 0 ? Math.max((count / max) * 100, 2) : 0
  return (
    <li>
      <div className="flex items-center justify-between gap-3 text-sm text-slate-800 dark:text-slate-200">
        <span>{label}</span>
        <span className="font-medium">{count}</span>
      </div>
      <div
        aria-hidden="true"
        className="mt-1 h-2 rounded bg-slate-200 dark:bg-slate-800"
      >
        <div
          className="h-2 rounded bg-slate-700 dark:bg-slate-300"
          style={{ width: `${width}%` }}
        />
      </div>
    </li>
  )
}

function Distribution({
  title,
  entries,
  renderLabel,
}: {
  title: string
  entries: DistributionEntry[]
  renderLabel: (key: string) => ReactNode
}) {
  const max = Math.max(...entries.map((entry) => entry.count), 0)
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
        {title}
      </h3>
      <ul className="mt-2 flex flex-col gap-2" aria-label={title}>
        {entries.map((entry) => (
          <BarRow
            key={entry.key}
            label={renderLabel(entry.key)}
            count={entry.count}
            max={max}
          />
        ))}
      </ul>
    </div>
  )
}

/** Severity and category distribution: answers "how serious, and of what
 * kind, are the problems found?". */
export function FindingDistribution({
  findings,
  findingsHref,
}: {
  findings: readonly FindingItem[]
  findingsHref: ReactNode
}) {
  return (
    <section aria-labelledby="distribution-heading">
      <h2 id="distribution-heading" className={HEADING_CLASS}>
        What was found
      </h2>
      {findings.length === 0 ? (
        <p className={`mt-2 ${MUTED_CLASS}`}>No findings were identified.</p>
      ) : (
        <div className="mt-3 grid gap-6 sm:grid-cols-2">
          <Distribution
            title="By severity"
            entries={severityDistribution(findings)}
            renderLabel={(key) => <FindingSeverityBadge severity={key} />}
          />
          <Distribution
            title="By kind of problem"
            entries={categoryDistribution(findings)}
            renderLabel={categoryLabel}
          />
        </div>
      )}
      {findingsHref}
    </section>
  )
}

/** Answers "where in the file should I look first?". */
export function ColumnsWithMostFindings({
  findings,
}: {
  findings: readonly FindingItem[]
}) {
  const columns = columnsWithMostFindings(findings)
  const max = Math.max(...columns.map((column) => column.count), 0)
  return (
    <section aria-labelledby="columns-heading">
      <h2 id="columns-heading" className={HEADING_CLASS}>
        Columns with the most findings
      </h2>
      {columns.length === 0 ? (
        <p className={`mt-2 ${MUTED_CLASS}`}>
          No finding points at a specific column.
        </p>
      ) : (
        <ul className="mt-3 flex max-w-xl flex-col gap-2">
          {columns.map((column) => (
            <BarRow
              key={column.name}
              label={column.name}
              count={column.count}
              max={max}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many
}

function Figure({
  term,
  value,
  note,
}: {
  term: string
  value: ReactNode
  note?: ReactNode
}) {
  return (
    <div className="rounded border border-slate-200 p-3 dark:border-slate-800">
      <dt className="text-sm font-medium text-slate-600 dark:text-slate-400">
        {term}
      </dt>
      <dd className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">
        {value}
      </dd>
      {note && <dd className={`mt-1 ${MUTED_CLASS}`}>{note}</dd>}
    </div>
  )
}

function RowsAffectedFigure({ summary }: { summary: AnalysisSummaryResponse }) {
  const share =
    summary.row_count > 0 ? summary.rows_affected / summary.row_count : null
  const unlocated = summary.findings_without_row_detail
  return (
    <Figure
      term="Rows affected"
      value={
        <>
          {summary.rows_affected.toLocaleString()}
          <span className="text-sm font-normal text-slate-500 dark:text-slate-400">
            {' '}
            of {summary.row_count.toLocaleString()} (
            {share === null ? 'not measured' : formatShare(share)})
          </span>
        </>
      }
      note={
        <>
          Rows that at least one finding points at, each counted once.
          {unlocated > 0 && (
            <>
              {' '}
              {unlocated}{' '}
              {plural(unlocated, 'finding concerns', 'findings concern')} a
              whole column or the whole file and{' '}
              {plural(unlocated, 'names', 'name')} no row, so the other rows are
              not necessarily clean.
            </>
          )}
        </>
      }
    />
  )
}

function CompletenessFigure({ summary }: { summary: AnalysisSummaryResponse }) {
  const { completeness } = summary
  const filledShare =
    completeness.missing_share === null ? null : 1 - completeness.missing_share
  const scopeNote =
    completeness.scope === 'full'
      ? `Measured on all ${completeness.population_size.toLocaleString()} rows.`
      : `Measured on a sample of ${completeness.sample_size.toLocaleString()} of ${completeness.population_size.toLocaleString()} rows, not the whole file.`
  return (
    <Figure
      term="Cells filled in"
      value={
        completeness.cells_missing === 0 && completeness.cells_total > 0
          ? '100%'
          : formatShare(filledShare)
      }
      note={
        <>
          {completeness.cells_missing.toLocaleString()} of{' '}
          {completeness.cells_total.toLocaleString()} cells are empty.{' '}
          {scopeNote}
        </>
      }
    />
  )
}

function ReviewProgressFigure({
  findings,
}: {
  findings: readonly FindingItem[]
}) {
  const progress = reviewProgress(findings)
  return (
    <Figure
      term="Review progress"
      value={
        <>
          {progress.reviewed}
          <span className="text-sm font-normal text-slate-500 dark:text-slate-400">
            {' '}
            of {progress.total} {plural(progress.total, 'finding', 'findings')}{' '}
            reviewed
          </span>
        </>
      }
      note={
        progress.total === 0
          ? 'There is nothing to review.'
          : progress.byState
              .map((entry) => `${reviewStateLabel(entry.key)}: ${entry.count}`)
              .join(' · ')
      }
    />
  )
}

/** The headline figures. The summary figures come from the server because
 * the list responses cannot answer them (distinct rows, completeness and
 * its scope); a failed summary request never blocks the rest of the page. */
export function AtAGlance({
  summary,
  summaryState,
  findings,
}: {
  summary: AnalysisSummaryResponse | undefined
  summaryState: 'loading' | 'error' | 'ready'
  findings: readonly FindingItem[]
}) {
  return (
    <section aria-labelledby="glance-heading">
      <h2 id="glance-heading" className={HEADING_CLASS}>
        At a glance
      </h2>
      <dl className="mt-3 grid gap-3 sm:grid-cols-3">
        {summaryState === 'ready' && summary ? (
          <>
            <RowsAffectedFigure summary={summary} />
            <CompletenessFigure summary={summary} />
          </>
        ) : (
          <div className="sm:col-span-2">
            {summaryState === 'loading' ? (
              <p role="status" aria-live="polite" className={MUTED_CLASS}>
                Loading figures…
              </p>
            ) : (
              <p
                role="alert"
                className="text-sm text-red-700 dark:text-red-300"
              >
                Row and completeness figures could not be loaded.
              </p>
            )}
          </div>
        )}
        <ReviewProgressFigure findings={findings} />
      </dl>
      <p className={`mt-3 ${MUTED_CLASS}`}>
        These figures come from TrustTable&apos;s built-in checks. AI
        explanations are optional and are prepared separately for each finding
        you ask about.
      </p>
    </section>
  )
}
