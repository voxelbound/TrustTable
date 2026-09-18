import { createBrowserRouter, redirect } from 'react-router'
import { AnalysisLayoutRoute } from './features/analysis/AnalysisLayoutRoute'
import { ContextRoute } from './features/analysis/ContextRoute'
import { FindingDetailRoute } from './features/analysis/FindingDetailRoute'
import { FindingsRoute } from './features/analysis/FindingsRoute'
import { OverviewRoute } from './features/analysis/OverviewRoute'
import { StartRoute } from './features/analysis/StartRoute'

/**
 * React Router Data Mode router (`UI-01`, `WP-025`; `findings/:findingId`
 * added by `WP-028`; `context` added by `WP-064`, `UI-02` slice 2) —
 * replaces `FND-01`'s placeholder route with the real investigation
 * shell.
 *
 * `/` redirects to `/analyses/new`: no analysis list/dashboard exists
 * yet (no persistence, `DB-01` not built) — `WP-025`'s Recorded
 * assumption 2. `docs/ui-specification.md` §3's remaining route tree
 * (`/rules`, `/report`, `/technical`) remains open.
 */
export const router = createBrowserRouter([
  {
    path: '/',
    loader: () => redirect('/analyses/new'),
  },
  {
    path: '/analyses/new',
    element: <StartRoute />,
  },
  {
    path: '/analyses/:analysisId',
    element: <AnalysisLayoutRoute />,
    children: [
      { path: 'overview', element: <OverviewRoute /> },
      { path: 'findings', element: <FindingsRoute /> },
      { path: 'findings/:findingId', element: <FindingDetailRoute /> },
      { path: 'context', element: <ContextRoute /> },
    ],
  },
])
