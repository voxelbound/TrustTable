import { createBrowserRouter, redirect } from 'react-router'
import { AnalysisLayoutRoute } from './features/analysis/AnalysisLayoutRoute'
import { ContextRoute } from './features/analysis/ContextRoute'
import { FindingDetailRoute } from './features/analysis/FindingDetailRoute'
import { FindingsRoute } from './features/analysis/FindingsRoute'
import { OverviewRoute } from './features/analysis/OverviewRoute'
import { ReportRoute } from './features/analysis/ReportRoute'
import { RulesRoute } from './features/analysis/RulesRoute'
import { TechnicalRoute } from './features/analysis/TechnicalRoute'
import { ConfigureRoute } from './features/workspace/ConfigureRoute'
import { WorkspaceRoute } from './features/workspace/WorkspaceRoute'

/**
 * React Router Data Mode router (`UI-01`, `WP-025`; `findings/:findingId`
 * added by `WP-028`; `context` added by `WP-064`, `UI-02` slice 2;
 * `report` added by `UI-03` slice 2; `rules` by `UI-03` slice 3;
 * `technical` by `UI-03` slice 5) —
 * replaces `FND-01`'s placeholder route with the real investigation
 * shell.
 *
 * `UX-02` (`docs/decision-log.md` D-068): `/` is the Workspace, where choosing
 * a file stages it and opens `/configure` (the staged reference is kept in
 * tab-scoped storage, never in the address). `/analyses/new`, the former Start
 * screen, stays reachable and redirects to `/`. No analysis list exists yet
 * (`UX-03`).
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <WorkspaceRoute />,
  },
  {
    path: '/configure',
    element: <ConfigureRoute />,
  },
  {
    path: '/analyses/new',
    loader: () => redirect('/'),
  },
  {
    path: '/analyses/:analysisId',
    element: <AnalysisLayoutRoute />,
    children: [
      { path: 'overview', element: <OverviewRoute /> },
      { path: 'findings', element: <FindingsRoute /> },
      { path: 'findings/:findingId', element: <FindingDetailRoute /> },
      { path: 'context', element: <ContextRoute /> },
      { path: 'report', element: <ReportRoute /> },
      { path: 'rules', element: <RulesRoute /> },
      { path: 'technical', element: <TechnicalRoute /> },
    ],
  },
])
