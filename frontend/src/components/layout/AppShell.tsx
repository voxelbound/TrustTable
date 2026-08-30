import type { ReactNode } from 'react'
import { Link } from 'react-router'

export interface AppShellProps {
  datasetName?: string
  statusText?: string
  children: ReactNode
}

/** Minimal top-level chrome (`docs/ui-specification.md` §3's documented
 * analysis-layout contents, bounded to what this package implements:
 * product name plus dataset name/status when on an analysis route — see
 * `WP-025`'s Recorded assumption 6 for what is deliberately not built
 * yet). */
export function AppShell({ datasetName, statusText, children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="border-b border-slate-200 px-6 py-4 dark:border-slate-800">
        <div className="mx-auto flex max-w-4xl items-center justify-between">
          <Link to="/" className="text-lg font-semibold">
            TrustTable
          </Link>
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
