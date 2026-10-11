import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import type { RowContextResponse } from '../../api'
import {
  affectedRowPosition,
  resolveAnchorRow,
  shownCell,
} from '../../domain/inspector'
import { useFindingDetail, useFindingRowContext } from './api'
import { carriedSearch } from './findingListView'

const INITIAL_WINDOW = 5
const EXPAND_STEP = 10
/** The server's own per-side maximum is authoritative (`max_window` in the
 * response); this only bounds what the screen asks for before it knows it. */
const CLIENT_MAX_WINDOW = 25
const ROW_PARAM = 'row'

const LINK_CLASS =
  'rounded border border-slate-300 px-2 py-1 text-sm font-medium text-slate-900 ' +
  'hover:bg-slate-100 dark:border-slate-600 dark:text-slate-100 dark:hover:bg-slate-800'
const DISABLED_CLASS =
  'rounded border border-slate-200 px-2 py-1 text-sm text-slate-400 ' +
  'dark:border-slate-800 dark:text-slate-600'
const BUTTON_CLASS =
  'text-sm font-medium text-slate-900 underline dark:text-slate-100'

/** The finding-scoped data inspector (`UX-06` part a, slice S5, D-073;
 * `docs/ui-specification.md` §12.4).
 *
 * A read-only grid of a finding's own affected rows with their neighbours:
 * it scrolls both ways, keeps the column headings and the row numbers in
 * view, marks the affected rows and the affected columns, and steps to the
 * previous and next affected row. It is not a dataset browser: only rows the
 * finding itself names can be the centre of a window, and the server refuses
 * any other. Every value is rendered as text, never as markup, and a long
 * value stays shortened until the reader asks to see all of it. Seeing row
 * values here adds them to nothing else: not to what is sent to a model, not
 * to evidence, and not to a report or export. Observations and column-wide
 * findings are `UX-06` part b. */
export function FindingInspectorRoute() {
  const { analysisId, findingId } = useParams<{
    analysisId: string
    findingId: string
  }>()
  const [searchParams] = useSearchParams()
  const detailQuery = useFindingDetail(analysisId, findingId)

  const carried = new URLSearchParams(searchParams)
  carried.delete(ROW_PARAM)
  const carriedFilters = carriedSearch(carried)
  const findingLink = `/analyses/${analysisId ?? ''}/findings/${findingId ?? ''}${carriedFilters}`

  if (detailQuery.isLoading) {
    return (
      <p
        role="status"
        aria-live="polite"
        className="text-sm text-slate-600 dark:text-slate-400"
      >
        Loading the finding…
      </p>
    )
  }

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <div className="flex flex-col gap-4">
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {detailQuery.error?.message ?? 'This finding could not be loaded.'}
        </p>
        <Link to={findingLink} className={BUTTON_CLASS}>
          Back to the finding
        </Link>
      </div>
    )
  }

  const finding = detailQuery.data
  const anchorRow = resolveAnchorRow(
    finding.affected_row_numbers,
    searchParams.get(ROW_PARAM),
  )

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link to={findingLink} className={BUTTON_CLASS}>
          Back to the finding
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">
          Inspect the rows
        </h1>
        <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
          {finding.calculated_observation}
        </p>
      </div>

      {anchorRow === null ? (
        <p className="rounded border border-slate-200 p-3 text-sm text-slate-700 dark:border-slate-800 dark:text-slate-300">
          This finding does not point to particular rows, so there is nothing to
          inspect here. It concerns whole columns; the rows behind it are not
          listed.
        </p>
      ) : (
        <InspectorGrid
          key={`${findingId}:${anchorRow}`}
          analysisId={analysisId as string}
          findingId={finding.finding_id}
          affectedRows={finding.affected_row_numbers}
          affectedRowCount={finding.affected_row_count}
          affectedColumnKeys={finding.affected_columns.map(
            (column) => column.internal_key,
          )}
          anchorRow={anchorRow}
          carriedFilters={carried}
        />
      )}
    </div>
  )
}

interface InspectorGridProps {
  analysisId: string
  findingId: string
  affectedRows: number[]
  /** How many rows the finding says are affected; may exceed the list. */
  affectedRowCount: number
  affectedColumnKeys: string[]
  anchorRow: number
  carriedFilters: URLSearchParams
}

function rowHref(row: number, carriedFilters: URLSearchParams): string {
  const params = new URLSearchParams(carriedFilters)
  params.set(ROW_PARAM, String(row))
  return `?${params.toString()}`
}

function InspectorGrid({
  analysisId,
  findingId,
  affectedRows,
  affectedRowCount,
  affectedColumnKeys,
  anchorRow,
  carriedFilters,
}: InspectorGridProps) {
  const [windowSize, setWindowSize] = useState({
    before: INITIAL_WINDOW,
    after: INITIAL_WINDOW,
  })
  const [revealed, setRevealed] = useState<ReadonlySet<string>>(new Set())
  const query = useFindingRowContext(
    analysisId,
    findingId,
    anchorRow,
    windowSize,
  )

  const position = affectedRowPosition(affectedRows, anchorRow)
  // Navigation must not imply that every affected row can be visited unless
  // the finding actually lists them all.
  const everyRowListed = affectedRowCount <= affectedRows.length
  const data = query.data

  return (
    <div className="flex flex-col gap-3">
      {position && (
        <nav
          aria-label="Move between affected rows"
          className="flex flex-col gap-2 rounded border border-slate-200 p-3 dark:border-slate-800"
        >
          <p className="text-sm text-slate-700 dark:text-slate-300">
            Affected row {position.position} of {position.total}
            {everyRowListed
              ? '.'
              : `. Only ${position.total} of the ${affectedRowCount} affected rows can be visited here.`}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {position.previousRow !== null ? (
              <Link
                to={rowHref(position.previousRow, carriedFilters)}
                className={LINK_CLASS}
              >
                Previous affected row
              </Link>
            ) : (
              <span aria-disabled="true" className={DISABLED_CLASS}>
                Previous affected row
              </span>
            )}
            {position.nextRow !== null ? (
              <Link
                to={rowHref(position.nextRow, carriedFilters)}
                className={LINK_CLASS}
              >
                Next affected row
              </Link>
            ) : (
              <span aria-disabled="true" className={DISABLED_CLASS}>
                Next affected row
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {position.previousRow === null
              ? 'This is the first affected row. '
              : ''}
            {position.nextRow === null
              ? 'This is the last affected row; there is no wrap-around. '
              : ''}
            Row numbers are the ones used in findings, observations and rules;
            row 0 is the first row below the column headings.
          </p>
        </nav>
      )}

      {query.isLoading && (
        <p
          role="status"
          aria-live="polite"
          className="text-sm text-slate-600 dark:text-slate-400"
        >
          Loading rows…
        </p>
      )}

      {query.isError && (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">
            {query.error.message}
          </p>
          <button
            type="button"
            className={BUTTON_CLASS}
            onClick={() => void query.refetch()}
          >
            Try again
          </button>
        </div>
      )}

      {data && (
        <>
          <Grid
            data={data}
            affectedColumnKeys={affectedColumnKeys}
            revealed={revealed}
            onReveal={(key) =>
              setRevealed((current) => new Set(current).add(key))
            }
          />
          <WindowNote
            data={data}
            onShowMore={() =>
              setWindowSize((current) => ({
                before: Math.min(
                  current.before + EXPAND_STEP,
                  data.max_window || CLIENT_MAX_WINDOW,
                ),
                after: Math.min(
                  current.after + EXPAND_STEP,
                  data.max_window || CLIENT_MAX_WINDOW,
                ),
              }))
            }
            asked={windowSize}
          />
        </>
      )}
    </div>
  )
}

function WindowNote({
  data,
  onShowMore,
  asked,
}: {
  data: RowContextResponse
  onShowMore: () => void
  asked: { before: number; after: number }
}) {
  // A side that came back short of what was asked, and was not shortened for
  // size, has reached the start or end of the file: nothing more exists there.
  const atStart = data.truncated_at_start && !data.size_limited
  const atEnd = data.truncated_at_end && !data.size_limited
  const canAskForMore =
    !data.size_limited &&
    ((!data.truncated_at_start && asked.before < data.max_window) ||
      (!data.truncated_at_end && asked.after < data.max_window))

  return (
    <div className="flex flex-col items-start gap-1 text-sm text-slate-600 dark:text-slate-400">
      <p>
        Showing {data.rows.length} row{data.rows.length === 1 ? '' : 's'}, at
        most {data.max_window} either side of the affected row. This is a view
        of part of the file, not all of it.
      </p>
      {(atStart || atEnd) && (
        <p>
          {atStart && atEnd
            ? 'Both the start and the end of the file are shown.'
            : atStart
              ? 'The start of the file is shown.'
              : 'The end of the file is shown.'}
        </p>
      )}
      {data.size_limited && (
        <p>
          The rows are wide, so fewer rows are shown than the window allows, to
          keep the page manageable.
        </p>
      )}
      {canAskForMore && (
        <button type="button" className={BUTTON_CLASS} onClick={onShowMore}>
          Show more rows
        </button>
      )}
    </div>
  )
}

interface GridProps {
  data: RowContextResponse
  affectedColumnKeys: string[]
  revealed: ReadonlySet<string>
  onReveal: (key: string) => void
}

const HEAD_CELL =
  'sticky top-0 z-10 border-b border-slate-300 bg-white px-2 py-1 text-left ' +
  'font-medium text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300'

function Grid({ data, affectedColumnKeys, revealed, onReveal }: GridProps) {
  const affectedKeys = new Set(affectedColumnKeys)
  // A finding that names no column concerns the row as a whole.
  const columnIsAffected = (key: string) =>
    affectedKeys.size === 0 || affectedKeys.has(key)

  return (
    <div
      role="region"
      aria-label="Rows around the affected row"
      tabIndex={0}
      className="max-h-[60vh] overflow-auto rounded border border-slate-200 dark:border-slate-800"
    >
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr>
            <th
              scope="col"
              className={`${HEAD_CELL} left-0 z-20 whitespace-nowrap`}
            >
              Row
            </th>
            {data.columns.map((column) => (
              <th
                key={column.internal_key}
                scope="col"
                className={`${HEAD_CELL} whitespace-nowrap`}
              >
                {column.original_name}
                {affectedKeys.has(column.internal_key) && (
                  <span className="ml-1 rounded bg-amber-100 px-1 text-xs font-normal text-amber-900 dark:bg-amber-900 dark:text-amber-100">
                    affected
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr
              key={row.row_number}
              aria-current={row.is_anchor ? 'true' : undefined}
              className={
                row.is_anchor
                  ? 'bg-amber-100 dark:bg-amber-950'
                  : row.is_affected_by_finding
                    ? 'bg-amber-50 dark:bg-amber-950/50'
                    : undefined
              }
            >
              <th
                scope="row"
                // Sticky, so it needs a solid background of its own.
                className={`sticky left-0 z-10 whitespace-nowrap border-b border-slate-100 px-2 py-1 text-left font-medium text-slate-700 dark:border-slate-800 dark:text-slate-300 ${
                  row.is_anchor
                    ? 'bg-amber-100 dark:bg-amber-950'
                    : row.is_affected_by_finding
                      ? 'bg-amber-50 dark:bg-amber-950'
                      : 'bg-white dark:bg-slate-900'
                }`}
              >
                {row.row_number}
                {row.is_anchor && (
                  <span className="ml-1 text-xs font-normal">
                    (this affected row)
                  </span>
                )}
                {!row.is_anchor && row.is_affected_by_finding && (
                  <span className="ml-1 text-xs font-normal">(affected)</span>
                )}
              </th>
              {row.values.map((value, columnIndex) => {
                const column = data.columns[columnIndex]
                const marked =
                  row.is_affected_by_finding &&
                  column !== undefined &&
                  columnIsAffected(column.internal_key)
                const cellKey = `${row.row_number}:${columnIndex}`
                return (
                  <td
                    key={columnIndex}
                    className={`border-b border-slate-100 px-2 py-1 align-top text-slate-800 dark:border-slate-800 dark:text-slate-200 ${
                      marked
                        ? 'bg-amber-200 font-medium ring-1 ring-inset ring-amber-500 dark:bg-amber-800'
                        : ''
                    }`}
                  >
                    <Cell
                      value={value}
                      cellKey={cellKey}
                      revealed={revealed.has(cellKey)}
                      onReveal={onReveal}
                      columnName={column?.original_name ?? ''}
                      rowNumber={row.row_number}
                    />
                    {marked && (
                      <span className="sr-only"> (affected value)</span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Cell({
  value,
  cellKey,
  revealed,
  onReveal,
  columnName,
  rowNumber,
}: {
  value: string | null
  cellKey: string
  revealed: boolean
  onReveal: (key: string) => void
  columnName: string
  rowNumber: number
}) {
  if (value === null) {
    return null
  }
  const shown = shownCell(value)
  if (!shown.shortened || revealed) {
    return <span className="whitespace-pre-wrap break-words">{value}</span>
  }
  return (
    <span className="whitespace-pre-wrap break-words">
      {shown.text}…{' '}
      <button
        type="button"
        className="text-xs font-medium underline"
        aria-label={`Show all ${shown.length} characters of ${columnName} in row ${rowNumber}`}
        onClick={() => onReveal(cellKey)}
      >
        Show all {shown.length} characters
      </button>
    </span>
  )
}
