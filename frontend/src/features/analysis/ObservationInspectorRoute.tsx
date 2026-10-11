import { Link, useParams, useSearchParams } from 'react-router'
import { resolveAnchorRow, windowFromScoped } from '../../domain/inspector'
import { useAnalysisObservations, useObservationRowContext } from './api'
import {
  BUTTON_CLASS,
  Grid,
  RowNavigator,
  WindowNote,
  WindowStatus,
} from './InspectorWindow'
import { ROW_PARAM, useRevealed, useWindowSize } from './inspectorWindowState'

/** The data inspector reached from an observation's example rows (`UX-06`
 * part b, slice S5, D-074; `docs/ui-specification.md` §12.4).
 *
 * An observation states a pattern that can be seen in the data; it is not a
 * finding and says nothing about what is wrong. This screen shows the rows the
 * observation itself lists as examples, with their neighbours, and nothing
 * else: only those rows can be the centre of a window and the server refuses
 * any other. The rows are examples, so the screen never implies that they are
 * all the rows the observation counted. Values are rendered as text, never as
 * markup, and seeing them here adds them to nothing else. */
export function ObservationInspectorRoute() {
  const { analysisId, observationId } = useParams<{
    analysisId: string
    observationId: string
  }>()
  const [searchParams] = useSearchParams()
  const observationsQuery = useAnalysisObservations(analysisId)
  const backLink = `/analyses/${analysisId ?? ''}/overview`

  if (observationsQuery.isLoading) {
    return (
      <p
        role="status"
        aria-live="polite"
        className="text-sm text-slate-600 dark:text-slate-400"
      >
        Loading the observation…
      </p>
    )
  }

  const observation = observationsQuery.data?.items.find(
    (item) => item.observation_id === observationId,
  )

  if (observationsQuery.isError || !observation) {
    return (
      <div className="flex flex-col gap-4">
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {observationsQuery.isError
            ? 'The observation could not be loaded.'
            : 'This observation was not found.'}
        </p>
        <Link to={backLink} className={BUTTON_CLASS}>
          Back to the overview
        </Link>
      </div>
    )
  }

  const anchorRow = resolveAnchorRow(
    observation.affected_row_numbers,
    searchParams.get(ROW_PARAM),
  )
  const carried = new URLSearchParams(searchParams)
  carried.delete(ROW_PARAM)

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link to={backLink} className={BUTTON_CLASS}>
          Back to the overview
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100">
          Inspect the example rows
        </h1>
        <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
          {observation.summary}
        </p>
      </div>

      {anchorRow === null ? (
        <p className="rounded border border-slate-200 p-3 text-sm text-slate-700 dark:border-slate-800 dark:text-slate-300">
          This observation does not list example rows, so there is nothing to
          inspect here.
        </p>
      ) : (
        <ObservationGrid
          key={`${observation.observation_id}:${anchorRow}`}
          analysisId={analysisId as string}
          observationId={observation.observation_id}
          exampleRows={observation.affected_row_numbers}
          columnKeys={observation.affected_columns.map(
            (column) => column.internal_key,
          )}
          anchorRow={anchorRow}
          carriedFilters={carried}
        />
      )}
    </div>
  )
}

function ObservationGrid({
  analysisId,
  observationId,
  exampleRows,
  columnKeys,
  anchorRow,
  carriedFilters,
}: {
  analysisId: string
  observationId: string
  exampleRows: number[]
  columnKeys: string[]
  anchorRow: number
  carriedFilters: URLSearchParams
}) {
  const { windowSize, widen } = useWindowSize()
  const { revealed, reveal } = useRevealed()
  const query = useObservationRowContext(
    analysisId,
    observationId,
    anchorRow,
    windowSize,
  )
  const data = query.data ? windowFromScoped(query.data) : undefined

  return (
    <div className="flex flex-col gap-3">
      <RowNavigator
        rows={exampleRows}
        current={anchorRow}
        noun="example row"
        partialNote="These are examples; the observation may count more rows than it lists."
        carriedFilters={carriedFilters}
        footnote="Row numbers are the ones used in findings, observations and rules; row 0 is the first row below the column headings."
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
            affectedColumnKeys={columnKeys}
            revealed={revealed}
            onReveal={reveal}
            rowNoun="example"
            regionLabel="Rows around the example row"
          />
          <WindowNote
            data={data}
            onShowMore={() => widen(data.maxWindow)}
            asked={windowSize}
            centre="the example row"
          />
        </>
      )}
    </div>
  )
}
