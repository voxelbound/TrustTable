import { Link, useParams, useSearchParams } from 'react-router'
import {
  resolveAnchorRow,
  windowFromFinding,
  windowFromScoped,
} from '../../domain/inspector'
import {
  useColumnWideWindow,
  useFindingDetail,
  useFindingRowContext,
} from './api'
import { carriedSearch } from './findingListView'
import {
  BUTTON_CLASS,
  Grid,
  RowNavigator,
  WindowNote,
  WindowStatus,
} from './InspectorWindow'
import { ROW_PARAM, useRevealed, useWindowSize } from './inspectorWindowState'

const ROW_NUMBERS_NOTE =
  'Row numbers are the ones used in findings, observations and rules; row 0 is the first row below the column headings.'

/** The finding-scoped data inspector (`UX-06`, slice S5, D-073 and D-074;
 * `docs/ui-specification.md` §12.4).
 *
 * A read-only grid of a finding's own affected rows with their neighbours:
 * it scrolls both ways, keeps the column headings and the row numbers in
 * view, marks the affected rows and the affected columns, and steps to the
 * previous and next affected row. It is not a dataset browser: only rows the
 * server itself offers can be the centre of a window. For a finding that names
 * no rows (a column-wide finding) the server offers the example rows of
 * observations about the same columns and otherwise only the start of the
 * file, and the screen says which it is. Every value is rendered as text,
 * never as markup, and a long value stays shortened until the reader asks to
 * see all of it. Seeing row values here adds them to nothing else: not to what
 * is sent to a model, not to evidence, and not to a report or export. */
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
  const affectedColumnKeys = finding.affected_columns.map(
    (column) => column.internal_key,
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
        <ColumnWideWindow
          analysisId={analysisId as string}
          findingId={finding.finding_id}
          affectedColumnKeys={affectedColumnKeys}
          requestedRow={searchParams.get(ROW_PARAM)}
          carriedFilters={carried}
        />
      ) : (
        <InspectorGrid
          key={`${findingId}:${anchorRow}`}
          analysisId={analysisId as string}
          findingId={finding.finding_id}
          affectedRows={finding.affected_row_numbers}
          affectedRowCount={finding.affected_row_count}
          affectedColumnKeys={affectedColumnKeys}
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

function InspectorGrid({
  analysisId,
  findingId,
  affectedRows,
  affectedRowCount,
  affectedColumnKeys,
  anchorRow,
  carriedFilters,
}: InspectorGridProps) {
  const { windowSize, widen } = useWindowSize()
  const { revealed, reveal } = useRevealed()
  const query = useFindingRowContext(
    analysisId,
    findingId,
    anchorRow,
    windowSize,
  )

  // Navigation must not imply that every affected row can be visited unless
  // the finding actually lists them all.
  const everyRowListed = affectedRowCount <= affectedRows.length
  const data = query.data ? windowFromFinding(query.data) : undefined

  return (
    <div className="flex flex-col gap-3">
      <RowNavigator
        rows={affectedRows}
        current={anchorRow}
        noun="affected row"
        partialNote={
          everyRowListed
            ? null
            : `Only ${affectedRows.length} of the ${affectedRowCount} affected rows can be visited here.`
        }
        carriedFilters={carriedFilters}
        footnote={ROW_NUMBERS_NOTE}
      />

      <WindowStatus
        loading={query.isLoading}
        error={query.isError ? query.error.message : null}
        onRetry={() => void query.refetch()}
      />

      {data && (
        <>
          <Grid
            data={data}
            affectedColumnKeys={affectedColumnKeys}
            revealed={revealed}
            onReveal={reveal}
            rowNoun="affected"
            regionLabel="Rows around the affected row"
          />
          <WindowNote
            data={data}
            onShowMore={() => widen(data.maxWindow)}
            asked={windowSize}
            centre="the affected row"
          />
        </>
      )}
    </div>
  )
}

/** A finding that names no rows (`UX-06` part b, D-074). The server decides
 * where the window can be centred and says why: the example rows of
 * observations about the same columns, or only the start of the file. The
 * screen never presents the start of the file as an example of the finding. */
function ColumnWideWindow({
  analysisId,
  findingId,
  affectedColumnKeys,
  requestedRow,
  carriedFilters,
}: {
  analysisId: string
  findingId: string
  affectedColumnKeys: string[]
  requestedRow: string | null
  carriedFilters: URLSearchParams
}) {
  const { windowSize, widen } = useWindowSize()
  const { revealed, reveal } = useRevealed()
  const requested =
    requestedRow !== null && /^\d+$/.test(requestedRow)
      ? Number(requestedRow)
      : undefined
  const query = useColumnWideWindow(
    analysisId,
    findingId,
    requested,
    windowSize,
  )
  const scoped = query.data
  const data = scoped ? windowFromScoped(scoped) : undefined
  const current = scoped?.rows.find((row) => row.is_anchor)?.row_number
  const startOfFile = scoped?.anchor_source === 'start_of_file'
  const firstWindow = `?${carriedFilters.toString()}`

  return (
    <div className="flex flex-col gap-3">
      <p className="rounded border border-slate-200 p-3 text-sm text-slate-700 dark:border-slate-800 dark:text-slate-300">
        This finding concerns whole columns and does not name particular rows.
        {scoped === undefined
          ? ''
          : startOfFile
            ? ' Below is the start of the file, so you can see what the columns hold. It is not evidence of the finding, and no row is marked as affected; only a column heading marked "affected" shows what the finding is about.'
            : ' Below are example rows from observations about the same columns. They show what was counted; they are not rows this finding names, and other rows may be involved.'}
      </p>

      {scoped && !startOfFile && current !== undefined && (
        <RowNavigator
          rows={scoped.anchor_rows}
          current={current}
          noun="example row"
          partialNote="These are examples; the observations may count more rows."
          carriedFilters={carriedFilters}
          footnote={ROW_NUMBERS_NOTE}
        />
      )}

      <WindowStatus
        loading={query.isLoading}
        error={query.isError ? query.error.message : null}
        onRetry={() => void query.refetch()}
        extra={
          requested !== undefined ? (
            <Link to={firstWindow} className={BUTTON_CLASS}>
              Back to the first window
            </Link>
          ) : undefined
        }
      />

      {data && scoped && (
        <>
          <Grid
            data={data}
            affectedColumnKeys={affectedColumnKeys}
            revealed={revealed}
            onReveal={reveal}
            rowNoun="example"
            regionLabel={
              startOfFile
                ? 'Rows at the start of the file'
                : 'Rows around the example row'
            }
          />
          <WindowNote
            data={data}
            onShowMore={() => widen(data.maxWindow)}
            asked={windowSize}
            centre={startOfFile ? 'the first row' : 'the example row'}
          />
        </>
      )}
    </div>
  )
}
