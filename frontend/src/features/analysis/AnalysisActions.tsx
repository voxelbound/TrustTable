import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { useCancelAnalysis, useDeleteAnalysis, useRetryAnalysis } from './api'

export interface AnalysisActionsProps {
  analysisId: string
  /** From `AnalysisStatusResponse.cancellable` — the API's own answer. */
  cancellable: boolean
  /** From `AnalysisStatusResponse.retryable` — only failed analyses. */
  retryable: boolean
}

/** Analysis lifecycle controls (`docs/ui-specification.md` §3, §4.3;
 * `UI-03` slice 1): cancel, retry and delete. Availability follows the
 * status response, never a client-side guess about which states the API
 * accepts. Delete is permanent and always goes through a confirmation. */
export function AnalysisActions({
  analysisId,
  cancellable,
  retryable,
}: AnalysisActionsProps) {
  const navigate = useNavigate()
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const cancelMutation = useCancelAnalysis(analysisId)
  const retryMutation = useRetryAnalysis(analysisId)
  const deleteMutation = useDeleteAnalysis(analysisId)

  const busy =
    cancelMutation.isPending ||
    retryMutation.isPending ||
    deleteMutation.isPending

  const handleRetry = () => {
    retryMutation.mutate(undefined, {
      onSuccess: (response) => {
        void navigate(`/analyses/${response.analysis.analysis_id}`)
      },
    })
  }

  const handleConfirmDelete = () => {
    deleteMutation.mutate(undefined, {
      onSuccess: () => {
        setConfirmingDelete(false)
        void navigate('/analyses/new')
      },
      onError: () => setConfirmingDelete(false),
    })
  }

  const error =
    cancelMutation.error ?? retryMutation.error ?? deleteMutation.error

  return (
    <section aria-label="Analysis actions" className="mt-4">
      <div className="flex flex-wrap gap-3">
        {cancellable && (
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => cancelMutation.mutate()}
          >
            {cancelMutation.isPending ? 'Cancelling…' : 'Cancel analysis'}
          </Button>
        )}
        {retryable && (
          <Button disabled={busy} onClick={handleRetry}>
            {retryMutation.isPending ? 'Retrying…' : 'Retry analysis'}
          </Button>
        )}
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => setConfirmingDelete(true)}
        >
          Delete analysis
        </Button>
      </div>
      {error && (
        <div className="mt-3">
          <Alert variant="error" title="That action could not be completed">
            {error.message}
          </Alert>
        </div>
      )}
      {confirmingDelete && (
        <ConfirmDialog
          title="Delete this analysis?"
          confirmLabel="Delete permanently"
          pending={deleteMutation.isPending}
          onConfirm={handleConfirmDelete}
          onCancel={() => setConfirmingDelete(false)}
        >
          This permanently removes the uploaded file, its findings, rules,
          reviews and every report generated from it. This cannot be undone.
        </ConfirmDialog>
      )}
    </section>
  )
}
