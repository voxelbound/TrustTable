import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useFindingAiEnrichment, useStartFindingAiEnrichment } from './api'

const EXPLANATION_QUERY_KEY = 'analysis-finding-explanation'

/** The AI part of one finding (`UX-05b`, `docs/decision-log.md` D-066 item 7),
 * kept apart from the built-in guidance: the guidance is on the page at once
 * and never waits on a model. This panel only reports where the optional AI
 * explanation is: preparing, failed, or busy. A ready result needs no panel,
 * because it replaces the guidance in the sections around it and says where it
 * came from.
 *
 * Opening a finding is the request for its AI explanation, as it always was;
 * nothing is requested for findings that are not opened. It is requested once
 * per finding and state, so a failure is never retried in a loop: a failed or
 * refused request waits for the person to ask again. The status is polled only
 * while it is preparing, and the explanation is read again the moment the
 * result is ready or has failed. All text shown here is fixed; no model output
 * is ever rendered by this component. */
export function FindingAiPanel({
  analysisId,
  findingId,
}: {
  analysisId: string
  findingId: string
}) {
  const queryClient = useQueryClient()
  const status = useFindingAiEnrichment(analysisId, findingId)
  const start = useStartFindingAiEnrichment(analysisId, findingId)
  const state = status.data?.state
  const requestedFor = useRef<string | null>(null)
  const previousState = useRef<string | undefined>(undefined)
  const { mutate } = start

  useEffect(() => {
    if (state === 'ready') {
      // A later change (new context, new model) may make it stale again.
      requestedFor.current = null
    }
    if (state !== 'not_requested' && state !== 'stale') {
      return
    }
    const key = `${analysisId}/${findingId}/${state}`
    if (requestedFor.current === key) {
      return
    }
    requestedFor.current = key
    mutate()
  }, [analysisId, findingId, state, mutate])

  useEffect(() => {
    const before = previousState.current
    previousState.current = state
    if (
      before !== undefined &&
      before !== state &&
      (state === 'ready' || state === 'failed')
    ) {
      void queryClient.invalidateQueries({
        queryKey: [EXPLANATION_QUERY_KEY, analysisId, findingId],
      })
    }
  }, [state, queryClient, analysisId, findingId])

  if (start.isError) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="mt-2 flex flex-wrap items-center gap-3 text-sm text-slate-700 dark:text-slate-300"
      >
        <span>{start.error.message}</span>
        <button
          type="button"
          onClick={() => {
            mutate()
          }}
          className="rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-900 dark:border-slate-700 dark:text-slate-100"
        >
          Try AI explanation again
        </button>
      </div>
    )
  }

  if (
    start.isPending ||
    state === 'preparing' ||
    state === 'not_requested' ||
    state === 'stale'
  ) {
    return (
      <p
        role="status"
        aria-live="polite"
        className="mt-2 text-sm text-slate-600 dark:text-slate-400"
      >
        AI explanation: preparing… The built-in guidance on this page is
        available now.
      </p>
    )
  }

  if (state === 'failed') {
    return (
      <div
        role="status"
        aria-live="polite"
        className="mt-2 flex flex-wrap items-center gap-3 text-sm text-slate-700 dark:text-slate-300"
      >
        <span>
          The AI explanation could not be completed, so the built-in guidance is
          shown.
        </span>
        <button
          type="button"
          onClick={() => {
            mutate()
          }}
          className="rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-900 dark:border-slate-700 dark:text-slate-100"
        >
          Try AI explanation again
        </button>
      </div>
    )
  }

  // `unavailable` (no AI is configured), `ready` (the sections show it), or a
  // status that could not be read: nothing to add, the guidance stands.
  return null
}
