import { createBrowserRouter, redirect } from 'react-router'
import { AnalysisLayoutRoute } from './features/analysis/AnalysisLayoutRoute'
import { FindingsRoute } from './features/analysis/FindingsRoute'
import { OverviewRoute } from './features/analysis/OverviewRoute'
import { StartRoute } from './features/analysis/StartRoute'

/**
 * React Router Data Mode router (`UI-01`, `WP-025`) — replaces `FND-01`'s
 * placeholder route with the real investigation shell.
 *
 * `/` redirects to `/analyses/new`: no analysis list/dashboard exists
 * yet (no persistence, `DB-01` not built) — `WP-025`'s Recorded
 * assumption 2. `docs/ui-specification.md` §3's fuller route tree
 * (`/context`, `/findings/:findingId`, `/rules`, `/report`,
 * `/technical`) is not built by this package; see the work package's
 * `backlog_remaining` disclosure.
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
    ],
  },
])
