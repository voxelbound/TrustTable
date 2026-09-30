import { Link, Outlet, useNavigate, useParams } from 'react-router'
import { AppShell } from '../../components/layout/AppShell'
import { AnalysisStageProgress } from '../../components/provenance/AnalysisStageProgress'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { AnalysisActions } from './AnalysisActions'
import { useAnalysisResource, useAnalysisStatus } from './api'

const RESOURCE_STATES = new Set(['completed', 'failed', 'cancelled'])

/** The analysis layout route (`docs/ui-specification.md` §3). Polls
 * status while in progress (`AnalysisStageProgress`), then branches on
 * the terminal outcome. Renders `Outlet` (Overview/Findings) only once
 * `completed`. */
export function AnalysisLayoutRoute() {
  const { analysisId } = useParams<{ analysisId: string }>()
  const navigate = useNavigate()
  const statusQuery = useAnalysisStatus(analysisId)
  const state = statusQuery.data?.state
  const isCompleted = state === 'completed'

  const resourceQuery = useAnalysisResource(analysisId, {
    enabled: Boolean(state) && RESOURCE_STATES.has(state as string),
  })
  const datasetName = resourceQuery.data?.dataset.original_filename

  const handleReturnToStart = () => {
    void navigate('/analyses/new')
  }

  const actions = analysisId ? (
    <AnalysisActions
      analysisId={analysisId}
      cancellable={statusQuery.data?.cancellable ?? false}
      retryable={statusQuery.data?.retryable ?? false}
    />
  ) : null

  if (statusQuery.isLoading) {
    return (
      <AppShell>
        <p
          role="status"
          aria-live="polite"
          className="text-sm text-slate-600 dark:text-slate-400"
        >
          Loading analysis…
        </p>
      </AppShell>
    )
  }

  if (statusQuery.isError) {
    return (
      <AppShell>
        <Alert variant="error" title="Could not load this analysis">
          {statusQuery.error.message}
        </Alert>
        <Button className="mt-4" onClick={handleReturnToStart}>
          Return to start
        </Button>
      </AppShell>
    )
  }

  if (state === 'failed') {
    const failureMessage =
      resourceQuery.data?.failure?.message ??
      'The analysis could not be completed. No partial or unreliable results are shown.'
    return (
      <AppShell datasetName={datasetName} statusText="Failed">
        <Alert variant="error" title="This analysis failed">
          {failureMessage}
        </Alert>
        <Button className="mt-4" onClick={handleReturnToStart}>
          Return to start
        </Button>
        {actions}
      </AppShell>
    )
  }

  if (state === 'cancelled') {
    return (
      <AppShell datasetName={datasetName} statusText="Cancelled">
        <Alert variant="warning" title="This analysis was cancelled">
          No results are available for a cancelled analysis.
        </Alert>
        <Button className="mt-4" onClick={handleReturnToStart}>
          Return to start
        </Button>
        {actions}
      </AppShell>
    )
  }

  if (!isCompleted) {
    return (
      <AppShell statusText="In progress">
        <AnalysisStageProgress state={state ?? 'queued'} />
        {actions}
      </AppShell>
    )
  }

  return (
    <AppShell datasetName={datasetName} statusText="Completed">
      {actions}
      <nav aria-label="Analysis sections" className="mt-4 flex gap-4 text-sm">
        <Link
          to={`/analyses/${analysisId ?? ''}/overview`}
          className="font-medium text-slate-900 underline dark:text-slate-100"
        >
          Overview
        </Link>
        <Link
          to={`/analyses/${analysisId ?? ''}/rules`}
          className="font-medium text-slate-900 underline dark:text-slate-100"
        >
          Rules
        </Link>
        <Link
          to={`/analyses/${analysisId ?? ''}/report`}
          className="font-medium text-slate-900 underline dark:text-slate-100"
        >
          Report
        </Link>
        <Link
          to={`/analyses/${analysisId ?? ''}/technical`}
          className="font-medium text-slate-900 underline dark:text-slate-100"
        >
          Technical
        </Link>
      </nav>
      <div className="mt-6">
        <Outlet />
      </div>
    </AppShell>
  )
}
