import type { ReactNode } from 'react'
import { Link } from 'react-router'
import {
  affectedRowPosition,
  shownCell,
  type WindowView,
} from '../../domain/inspector'
import { rowHref, type WindowSize } from './inspectorWindowState'

/** The parts every inspector screen shares (`UX-06`, D-073 and D-074): the
 * grid, its window note, the move-between-rows control and the window size
 * state. A screen decides what the rows mean (a finding's affected rows, an
 * observation's example rows, the start of a file); this only shows them.
 *
 * Every value is rendered as a React text node, never as markup, and a long
 * value stays shortened until the reader asks to see all of it. */

export const LINK_CLASS =
  'rounded border border-slate-300 px-2 py-1 text-sm font-medium text-slate-900 ' +
  'hover:bg-slate-100 dark:border-slate-600 dark:text-slate-100 dark:hover:bg-slate-800'
export const DISABLED_CLASS =
  'rounded border border-slate-200 px-2 py-1 text-sm text-slate-400 ' +
  'dark:border-slate-800 dark:text-slate-600'
export const BUTTON_CLASS =
  'text-sm font-medium text-slate-900 underline dark:text-slate-100'

/** Previous and next among the rows the screen can visit, with the position
 * stated. `noun` is how the screen names those rows ("affected row",
 * "example row"); `partialNote` is shown when only some of the rows that
 * exist can be visited, so the control never implies more than it reaches. */
export function RowNavigator({
  rows,
  current,
  noun,
  partialNote,
  carriedFilters,
  footnote,
}: {
  rows: readonly number[]
  current: number
  noun: string
  partialNote: string | null
  carriedFilters: URLSearchParams
  footnote: string
}) {
  const position = affectedRowPosition(rows, current)
  if (!position) {
    return null
  }
  const capitalised = `${noun.charAt(0).toUpperCase()}${noun.slice(1)}`
  return (
    <nav
      aria-label={`Move between ${noun}s`}
      className="flex flex-col gap-2 rounded border border-slate-200 p-3 dark:border-slate-800"
    >
      <p className="text-sm text-slate-700 dark:text-slate-300">
        {capitalised} {position.position} of {position.total}
        {partialNote === null ? '.' : `. ${partialNote}`}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {position.previousRow !== null ? (
          <Link
            to={rowHref(position.previousRow, carriedFilters)}
            className={LINK_CLASS}
          >
            Previous {noun}
          </Link>
        ) : (
          <span aria-disabled="true" className={DISABLED_CLASS}>
            Previous {noun}
          </span>
        )}
        {position.nextRow !== null ? (
          <Link
            to={rowHref(position.nextRow, carriedFilters)}
            className={LINK_CLASS}
          >
            Next {noun}
          </Link>
        ) : (
          <span aria-disabled="true" className={DISABLED_CLASS}>
            Next {noun}
          </span>
        )}
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        {position.previousRow === null ? `This is the first ${noun}. ` : ''}
        {position.nextRow === null
          ? `This is the last ${noun}; there is no wrap-around. `
          : ''}
        {footnote}
      </p>
    </nav>
  )
}

/** Loading and error lines every inspector read shares. */
export function WindowStatus({
  loading,
  error,
  onRetry,
  extra,
}: {
  loading: boolean
  error: string | null
  onRetry: () => void
  extra?: ReactNode
}) {
  return (
    <>
      {loading && (
        <p
          role="status"
          aria-live="polite"
          className="text-sm text-slate-600 dark:text-slate-400"
        >
          Loading rows…
        </p>
      )}
      {error !== null && (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">
            {error}
          </p>
          <button type="button" className={BUTTON_CLASS} onClick={onRetry}>
            Try again
          </button>
          {extra}
        </div>
      )}
    </>
  )
}

export function WindowNote({
  data,
  onShowMore,
  asked,
  centre,
}: {
  data: WindowView
  onShowMore: () => void
  asked: WindowSize
  /** What the window is centred on, in words ("the affected row"). */
  centre: string
}) {
  // A side that came back short of what was asked, and was not shortened for
  // size, has reached the start or end of the file: nothing more exists there.
  const atStart = data.truncatedAtStart && !data.sizeLimited
  const atEnd = data.truncatedAtEnd && !data.sizeLimited
  const canAskForMore =
    !data.sizeLimited &&
    ((!data.truncatedAtStart && asked.before < data.maxWindow) ||
      (!data.truncatedAtEnd && asked.after < data.maxWindow))

  return (
    <div className="flex flex-col items-start gap-1 text-sm text-slate-600 dark:text-slate-400">
      <p>
        Showing {data.rows.length} row{data.rows.length === 1 ? '' : 's'}, at
        most {data.maxWindow} either side of {centre}. This is a view of part of
        the file, not all of it.
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
      {data.sizeLimited && (
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

const HEAD_CELL =
  'sticky top-0 z-10 border-b border-slate-300 bg-white px-2 py-1 text-left ' +
  'font-medium text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300'

/** The grid. `rowNoun` names the marked rows in words as well as colour
 * ("affected", "example"); `regionLabel` is the scrollable region's name. */
export function Grid({
  data,
  affectedColumnKeys,
  revealed,
  onReveal,
  rowNoun,
  regionLabel,
}: {
  data: WindowView
  affectedColumnKeys: readonly string[]
  revealed: ReadonlySet<string>
  onReveal: (key: string) => void
  rowNoun: string
  regionLabel: string
}) {
  const affectedKeys = new Set(affectedColumnKeys)
  // A scope that names no column concerns the row as a whole.
  const columnIsAffected = (key: string) =>
    affectedKeys.size === 0 || affectedKeys.has(key)

  return (
    <div
      role="region"
      aria-label={regionLabel}
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
                key={column.internalKey}
                scope="col"
                className={`${HEAD_CELL} whitespace-nowrap`}
              >
                {column.originalName}
                {affectedKeys.has(column.internalKey) && (
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
              key={row.rowNumber}
              aria-current={row.isAnchor && row.isMarked ? 'true' : undefined}
              className={
                row.isAnchor && row.isMarked
                  ? 'bg-amber-100 dark:bg-amber-950'
                  : row.isMarked
                    ? 'bg-amber-50 dark:bg-amber-950/50'
                    : undefined
              }
            >
              <th
                scope="row"
                // Sticky, so it needs a solid background of its own.
                className={`sticky left-0 z-10 whitespace-nowrap border-b border-slate-100 px-2 py-1 text-left font-medium text-slate-700 dark:border-slate-800 dark:text-slate-300 ${
                  row.isAnchor && row.isMarked
                    ? 'bg-amber-100 dark:bg-amber-950'
                    : row.isMarked
                      ? 'bg-amber-50 dark:bg-amber-950'
                      : 'bg-white dark:bg-slate-900'
                }`}
              >
                {row.rowNumber}
                {row.isAnchor && row.isMarked && (
                  <span className="ml-1 text-xs font-normal">
                    (this {rowNoun} row)
                  </span>
                )}
                {!row.isAnchor && row.isMarked && (
                  <span className="ml-1 text-xs font-normal">({rowNoun})</span>
                )}
                {row.isAnchor && !row.isMarked && (
                  <span className="ml-1 text-xs font-normal">
                    (first row of the file)
                  </span>
                )}
              </th>
              {row.values.map((value, columnIndex) => {
                const column = data.columns[columnIndex]
                const marked =
                  row.isMarked &&
                  column !== undefined &&
                  columnIsAffected(column.internalKey)
                const cellKey = `${row.rowNumber}:${columnIndex}`
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
                      columnName={column?.originalName ?? ''}
                      rowNumber={row.rowNumber}
                    />
                    {marked && (
                      <span className="sr-only"> ({rowNoun} value)</span>
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
