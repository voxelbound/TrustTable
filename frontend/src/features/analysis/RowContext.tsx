import { useState } from 'react'
import { useFindingRowContext } from './api'

const DEFAULT_WINDOW_SIZE = 3
const EXPAND_STEP = 5
const CLIENT_MAX_WINDOW = 25
const INITIAL_WINDOW_SIZE = {
  before: DEFAULT_WINDOW_SIZE,
  after: DEFAULT_WINDOW_SIZE,
}

interface RowContextProps {
  analysisId: string
  findingId: string
  /** The finding's own affected `RowReference.row_number` values,
   * ascending (`FindingDetailResponse.affected_row_numbers`, `WP-038`). */
  affectedRowNumbers: number[]
}

/** The Finding Detail screen's "Row context" section
 * (`docs/ui-specification.md` §4.7, `FIND-01`, `WP-038`): an on-demand,
 * bounded physical-neighborhood read around one of a finding's own
 * affected rows, with an expand control and, for findings with more than
 * one affected row, Prev/Next navigation between them
 * (`project-ops/changes/CHG-001-investigation-ux-row-context.md` §3).
 * Renders nothing for a finding with zero affected rows — this
 * capability is not available for column-wide findings
 * (`docs/domain-model.md` §13). */
export function RowContext({
  analysisId,
  findingId,
  affectedRowNumbers,
}: RowContextProps) {
  const [anchorIndex, setAnchorIndex] = useState(0)
  const [windowSize, setWindowSize] = useState(INITIAL_WINDOW_SIZE)

  const anchorRow = affectedRowNumbers[anchorIndex]
  const query = useFindingRowContext(
    analysisId,
    findingId,
    anchorRow,
    windowSize,
  )

  if (affectedRowNumbers.length === 0) {
    return null
  }

  const hasMultipleAffectedRows = affectedRowNumbers.length > 1
  const canExpand =
    windowSize.before < CLIENT_MAX_WINDOW ||
    windowSize.after < CLIENT_MAX_WINDOW
  const isTruncated =
    query.data !== undefined &&
    (query.data.truncated_at_start || query.data.truncated_at_end)

  function handlePrevious() {
    setAnchorIndex((current) => Math.max(0, current - 1))
    setWindowSize(INITIAL_WINDOW_SIZE)
  }

  function handleNext() {
    setAnchorIndex((current) =>
      Math.min(affectedRowNumbers.length - 1, current + 1),
    )
    setWindowSize(INITIAL_WINDOW_SIZE)
  }

  function handleExpand() {
    setWindowSize((current) => ({
      before: Math.min(current.before + EXPAND_STEP, CLIENT_MAX_WINDOW),
      after: Math.min(current.after + EXPAND_STEP, CLIENT_MAX_WINDOW),
    }))
  }

  return (
    <section aria-labelledby="row-context-heading">
      <div className="flex items-center justify-between gap-2">
        <h2
          id="row-context-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Row context
        </h2>
        {hasMultipleAffectedRows && (
          <div className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
            <button
              type="button"
              onClick={handlePrevious}
              disabled={anchorIndex === 0}
              className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50 dark:border-slate-700"
            >
              Previous
            </button>
            <span>
              Affected row {anchorIndex + 1} of {affectedRowNumbers.length}
            </span>
            <button
              type="button"
              onClick={handleNext}
              disabled={anchorIndex === affectedRowNumbers.length - 1}
              className="rounded border border-slate-300 px-2 py-1 disabled:opacity-50 dark:border-slate-700"
            >
              Next
            </button>
          </div>
        )}
      </div>

      {query.isLoading && (
        <p
          role="status"
          aria-live="polite"
          className="mt-2 text-sm text-slate-600 dark:text-slate-400"
        >
          Loading row context…
        </p>
      )}

      {query.isError && (
        <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">
          {query.error.message}
        </p>
      )}

      {query.data && (
        <>
          <div className="mt-2 overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr>
                  {query.data.columns.map((column) => (
                    <th
                      key={column.internal_key}
                      scope="col"
                      className="border-b border-slate-300 px-2 py-1 text-left font-medium text-slate-700 dark:border-slate-700 dark:text-slate-300"
                    >
                      {column.original_name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {query.data.rows.map((row) => (
                  <tr
                    key={row.row_number}
                    aria-current={row.is_anchor ? 'true' : undefined}
                    className={
                      row.is_anchor
                        ? 'bg-amber-100 dark:bg-amber-900'
                        : row.is_affected_by_finding
                          ? 'bg-amber-50 dark:bg-amber-950/50'
                          : undefined
                    }
                  >
                    {row.values.map((value, columnIndex) => (
                      <td
                        key={columnIndex}
                        className="border-b border-slate-100 px-2 py-1 text-slate-800 dark:border-slate-800 dark:text-slate-200"
                      >
                        {value ?? ''}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {isTruncated && canExpand && (
            <button
              type="button"
              onClick={handleExpand}
              className="mt-2 text-sm font-medium text-slate-900 underline dark:text-slate-100"
            >
              Show more rows
            </button>
          )}
        </>
      )}
    </section>
  )
}
