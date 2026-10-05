import { useAnalysisObservations } from './api'

/** The read-only list of data observations (`DET-03` closure package 2).
 *
 * An observation states a pattern that can be seen in the data. It is not a
 * finding: it has no severity, confidence or priority, never changes the
 * trust assessment and says nothing about what is right or wrong. The list is
 * therefore deliberately plain (no badge, no sort by importance, no review or
 * dismiss control) and sits apart from the findings. A failed or empty
 * request never blocks the rest of the screen. */
export function ObservationsList({
  analysisId,
}: {
  analysisId: string | undefined
}) {
  const query = useAnalysisObservations(analysisId)

  return (
    <section aria-labelledby="observations-heading">
      <h2
        id="observations-heading"
        className="text-xl font-semibold text-slate-900 dark:text-slate-100"
      >
        Data observations
      </h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Patterns seen in the data. They do not affect the trust assessment and
        do not say what is wrong.
      </p>
      {query.isLoading ? (
        <p
          role="status"
          aria-live="polite"
          className="mt-2 text-sm text-slate-600 dark:text-slate-400"
        >
          Loading observations…
        </p>
      ) : query.isError ? (
        <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">
          Observations could not be loaded.
        </p>
      ) : (query.data?.items ?? []).length === 0 ? (
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          No observations were recorded.
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-3">
          {(query.data?.items ?? []).map((observation) => (
            <li
              key={observation.observation_id}
              className="rounded border border-slate-200 p-3 dark:border-slate-800"
            >
              <p className="text-sm text-slate-800 dark:text-slate-200">
                {observation.summary}
              </p>
              {observation.affected_row_numbers.length > 0 && (
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Example rows: {observation.affected_row_numbers.join(', ')}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
