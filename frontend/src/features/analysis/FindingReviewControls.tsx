import { useState, type FormEvent } from 'react'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import type { FindingReviewRequest } from '../../api'
import { REVIEW_STATES, reviewStateLabel } from '../../domain/finding'
import { useSaveFindingReview } from './api'

export interface FindingReviewControlsProps {
  analysisId: string
  findingId: string
  reviewState: string
  note: string | null
  dismissalReason: string | null
  reviewedAt: string | null
}

/** Review controls (`docs/ui-specification.md` §4.7, `UI-03` slice 4) over
 * `PUT .../findings/{finding_id}/review`. The shown "saved" state always
 * comes from the persisted detail response, never from local form state.
 * A review only records the manager's decision; it never changes the
 * finding's evidence, severity or the underlying data. The form is seeded
 * from the persisted review when the screen loads. */
export function FindingReviewControls({
  analysisId,
  findingId,
  reviewState,
  note,
  dismissalReason,
  reviewedAt,
}: FindingReviewControlsProps) {
  const mutation = useSaveFindingReview(analysisId, findingId)
  const [state, setState] = useState(reviewState)
  const [noteText, setNoteText] = useState(note ?? '')
  const [reason, setReason] = useState(dismissalReason ?? '')

  const dismissing = state === 'dismissed'
  const reasonMissing = dismissing && reason.trim() === ''

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (reasonMissing) {
      return
    }
    const trimmedNote = noteText.trim()
    const body: FindingReviewRequest = {
      state,
      note: trimmedNote === '' ? null : trimmedNote,
      dismissal_reason: dismissing ? reason.trim() : null,
    }
    mutation.mutate(body)
  }

  return (
    <section aria-labelledby="review-heading">
      <h2
        id="review-heading"
        className="text-xl font-semibold text-slate-900 dark:text-slate-100"
      >
        Review controls
      </h2>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
        Your review records your decision about this finding. It does not change
        the finding, its evidence or your data.
      </p>
      <p className="mt-2 text-sm text-slate-700 dark:text-slate-300">
        Current review: <strong>{reviewStateLabel(reviewState)}</strong>
        {reviewedAt && <> · saved {new Date(reviewedAt).toLocaleString()}</>}
      </p>
      <form
        onSubmit={handleSubmit}
        className="mt-3 flex max-w-xl flex-col gap-3"
      >
        <label className="flex flex-col gap-1 text-sm font-medium text-slate-800 dark:text-slate-200">
          Review state
          <select
            value={state}
            onChange={(event) => setState(event.target.value)}
            className="rounded border border-slate-300 bg-white p-2 font-normal dark:border-slate-600 dark:bg-slate-900"
          >
            {REVIEW_STATES.map((option) => (
              <option key={option} value={option}>
                {reviewStateLabel(option)}
              </option>
            ))}
          </select>
        </label>
        {dismissing && (
          <div className="flex flex-col gap-1">
            <label className="flex flex-col gap-1 text-sm font-medium text-slate-800 dark:text-slate-200">
              Dismissal reason (required)
              <input
                type="text"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                aria-required="true"
                aria-invalid={reasonMissing}
                aria-describedby={reasonMissing ? 'reason-error' : undefined}
                className="rounded border border-slate-300 bg-white p-2 font-normal dark:border-slate-600 dark:bg-slate-900"
              />
            </label>
            {reasonMissing && (
              <span
                id="reason-error"
                className="text-xs text-red-700 dark:text-red-300"
              >
                Enter a reason to dismiss this finding.
              </span>
            )}
          </div>
        )}
        <label className="flex flex-col gap-1 text-sm font-medium text-slate-800 dark:text-slate-200">
          Note (optional)
          <textarea
            value={noteText}
            onChange={(event) => setNoteText(event.target.value)}
            rows={3}
            className="rounded border border-slate-300 bg-white p-2 font-normal dark:border-slate-600 dark:bg-slate-900"
          />
        </label>
        <div>
          <Button type="submit" disabled={reasonMissing || mutation.isPending}>
            {mutation.isPending ? 'Saving…' : 'Save review'}
          </Button>
        </div>
        {mutation.isError && (
          <Alert variant="error" title="Could not save the review">
            {mutation.error.message}
          </Alert>
        )}
        {mutation.isSuccess && <Alert variant="success">Review saved.</Alert>}
      </form>
    </section>
  )
}
