import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Badge } from '../ui/Badge'

export interface AppShellProps {
  datasetName?: string
  statusText?: string
  children: ReactNode
}

/** Top-level chrome (`docs/ui-specification.md` §3): the product name, the
 * workspace navigation, and the dataset name/status on an analysis route.
 *
 * Navigation shows only what exists (`UX-02`, D-068): Home, and *Compare
 * datasets* as a disabled, labelled entry because comparison is planned and
 * not implemented. Analyses, Settings and Help appear when their slices ship;
 * until then they would be dead controls (`docs/ui-specification.md`
 * §12.1). */
export function AppShell({ datasetName, statusText, children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <Link to="/" className="text-lg font-semibold">
              TrustTable
            </Link>
            <nav aria-label="Workspace">
              <ul className="flex items-center gap-4 text-sm">
                <li>
                  <Link
                    to="/"
                    className="text-slate-700 underline-offset-2 hover:underline dark:text-slate-300"
                  >
                    Home
                  </Link>
                </li>
                <li
                  aria-disabled="true"
                  className="flex items-center gap-2 text-slate-500 dark:text-slate-400"
                >
                  <span>Compare datasets</span>
                  <Badge tone="info">Planned</Badge>
                </li>
              </ul>
            </nav>
          </div>
          {(datasetName || statusText) && (
            <div className="text-right text-sm">
              {datasetName && (
                <p className="font-medium text-slate-900 dark:text-slate-100">
                  {datasetName}
                </p>
              )}
              {statusText && (
                <p className="text-slate-600 dark:text-slate-400">
                  {statusText}
                </p>
              )}
            </div>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-6 py-8">{children}</main>
    </div>
  )
}
