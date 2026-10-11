import { NavLink, Outlet, useNavigate, useParams } from 'react-router'
import { AppShell } from '../../components/layout/AppShell'
import { AnalysisStageProgress } from '../../components/provenance/AnalysisStageProgress'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { useAdvancedMode } from '../../lib/advancedMode'
import { AnalysisActions } from './AnalysisActions'
import { useAnalysisResource, useAnalysisStatus } from './api'

const RESOURCE_STATES = new Set(['completed', 'failed', 'cancelled'])

/** The areas of a completed analysis, grouped as the workflow names them
 * (`UX-07`, D-075; `docs/ui-specification.md` §12.2). Every entry is a route
 * that exists; nothing is listed for a capability that is not built. */
const SECTION_GROUPS: {
  label: string
  items: { path: string; label: string; advancedOnly?: boolean }[]
}[] = [
  {
    label: 'Review',
    items: [
      { path: 'overview', label: 'Overview' },
      { path: 'findings', label: 'Findings' },
      { path: 'observations', label: 'Observations' },
      { path: 'context', label: 'About this data' },
    ],
  },
  {
    label: 'Act and Export',
    items: [
      { path: 'report', label: 'Reports' },
      { path: 'rules', label: 'Rules' },
      { path: 'technical', label: 'Technical details', advancedOnly: true },
    ],
  },
]

/** The analysis layout route (`docs/ui-specification.md` §3). An entry marked
 * `advancedOnly` is listed only in Advanced mode (`UX-08b`, D-077); its route
 * stays reachable by address. Polls
 * status while in progress (`AnalysisStageProgress`), then branches on
 * the terminal outcome. Renders `Outlet` (Overview/Findings) only once
 * `completed`. */
export function AnalysisLayoutRoute() {
  const { analysisId } = useParams<{ analysisId: string }>()
  const navigate = useNavigate()
  const [advanced] = useAdvancedMode()
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
      <nav
        aria-label="Analysis sections"
        className="mt-4 flex flex-wrap gap-x-10 gap-y-3 text-sm"
      >
        {SECTION_GROUPS.map((group) => (
          <div key={group.label}>
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
              {group.label}
            </p>
            <ul className="mt-1 flex flex-wrap gap-4">
              {group.items
                .filter((item) => advanced || !item.advancedOnly)
                .map((item) => (
                  <li key={item.path}>
                    <NavLink
                      to={`/analyses/${analysisId ?? ''}/${item.path}`}
                      className="font-medium text-slate-900 underline dark:text-slate-100"
                    >
                      {item.label}
                    </NavLink>
                  </li>
                ))}
            </ul>
          </div>
        ))}
      </nav>
      <div className="mt-6">
        <Outlet />
      </div>
    </AppShell>
  )
}
