import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import type { AnalysisHistoryItem } from '../../api'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import {
  useAnalysisHistory,
  useDeleteHistoryAnalysis,
  useRerunAnalysis,
} from './api'

const KILOBYTE = 1024
const MEGABYTE = KILOBYTE * 1024

function formatBytes(bytes: number): string {
  if (bytes >= MEGABYTE) {
    return `${(bytes / MEGABYTE).toFixed(1)} MB`
  }
  if (bytes >= KILOBYTE) {
    return `${(bytes / KILOBYTE).toFixed(1)} KB`
  }
  return `${bytes} bytes`
}

function formatWhen(value: string): string {
  const moment = new Date(value)
  return Number.isNaN(moment.getTime()) ? '' : moment.toLocaleString()
}

const STATE_LABELS: Record<AnalysisHistoryItem['state'], string> = {
  queued: 'Waiting to start',
  validating: 'In progress',
  parsing: 'In progress',
  profiling: 'In progress',
  detecting: 'In progress',
  completed: 'Finished',
  failed: 'Did not finish',
  cancelled: 'Cancelled',
}

const FINISHED_STATES = new Set<AnalysisHistoryItem['state']>([
  'completed',
  'failed',
  'cancelled',
])

function describeResult(item: AnalysisHistoryItem): string {
  if (item.state !== 'completed') {
    return STATE_LABELS[item.state]
  }
  const findings =
    item.finding_count === null || item.finding_count === undefined
      ? null
      : item.finding_count === 1
        ? '1 finding'
        : `${item.finding_count} findings`
  return findings === null
    ? STATE_LABELS.completed
    : `${STATE_LABELS.completed} · ${findings}`
}

/** Recent analyses on the Workspace (`UX-03`, `docs/decision-log.md` D-069).
 *
 * A bounded list of what is stored now, newest first. Each row can be opened,
 * run again (a new analysis from the stored file; the original is untouched) or
 * deleted after a confirmation. Names and labels come from the server and are
 * shown as plain text only. The list never shows or asks for a file's content
 * or fingerprint. */
export function RecentAnalyses() {
  const navigate = useNavigate()
  const history = useAnalysisHistory()
  const rerun = useRerunAnalysis()
  const remove = useDeleteHistoryAnalysis()
  const [deleting, setDeleting] = useState<AnalysisHistoryItem | null>(null)
  const busy = rerun.isPending || remove.isPending

  const handleRerun = (item: AnalysisHistoryItem) => {
    rerun.mutate(item.analysis_id, {
      onSuccess: (response) => {
        void navigate(`/analyses/${response.analysis.analysis_id}`)
      },
    })
  }

  const handleConfirmDelete = () => {
    if (deleting === null) {
      return
    }
    remove.mutate(deleting.analysis_id, {
      onSettled: () => setDeleting(null),
    })
  }

  const actionError = rerun.error ?? remove.error

  return (
    <section
      aria-labelledby="recent-heading"
      className="rounded border border-slate-200 p-6 dark:border-slate-800"
    >
      <h2
        id="recent-heading"
        className="text-lg font-medium text-slate-900 dark:text-slate-100"
      >
        Recent analyses
      </h2>

      {history.isPending && (
        <p
          role="status"
          className="mt-2 text-sm text-slate-600 dark:text-slate-400"
        >
          Loading your analyses…
        </p>
      )}

      {history.isError && (
        <div className="mt-3">
          <Alert variant="error" title="Could not load your analyses">
            {history.error.message}
          </Alert>
        </div>
      )}

      {history.data !== undefined && history.data.items.length === 0 && (
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          No analyses yet. Analyses you run appear here so you can open them
          again, run them again or delete them.
        </p>
      )}

      {history.data !== undefined && history.data.items.length > 0 && (
        <ul className="mt-3 flex flex-col divide-y divide-slate-200 dark:divide-slate-800">
          {history.data.items.map((item) => (
            <li
              key={item.analysis_id}
              className="flex flex-wrap items-center justify-between gap-3 py-3"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-slate-900 dark:text-slate-100">
                  {item.original_filename}
                  {item.source === 'demo' ? ' (sales demo)' : ''}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {describeResult(item)}
                  {item.trust_label ? ` · Trust: ${item.trust_label}` : ''}
                  {' · '}
                  {item.format === 'xlsx' ? 'Excel' : 'CSV'}
                  {item.selected_worksheet
                    ? ` · Worksheet ${item.selected_worksheet}`
                    : ''}
                  {' · '}
                  {formatBytes(item.byte_size)}
                  {' · '}
                  {formatWhen(item.created_at)}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Link
                  to={
                    item.state === 'completed'
                      ? `/analyses/${item.analysis_id}/overview`
                      : `/analyses/${item.analysis_id}`
                  }
                  aria-label={`Open ${item.original_filename}`}
                  className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
                >
                  Open
                </Link>
                {FINISHED_STATES.has(item.state) && (
                  <Button
                    variant="secondary"
                    disabled={busy}
                    aria-label={`Run ${item.original_filename} again`}
                    onClick={() => handleRerun(item)}
                  >
                    Run again
                  </Button>
                )}
                <Button
                  variant="secondary"
                  disabled={busy}
                  aria-label={`Delete ${item.original_filename}`}
                  onClick={() => setDeleting(item)}
                >
                  Delete
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {actionError && (
        <div className="mt-3">
          <Alert variant="error" title="That action could not be completed">
            {actionError.message}
          </Alert>
        </div>
      )}

      {deleting !== null && (
        <ConfirmDialog
          title="Delete this analysis?"
          confirmLabel="Delete permanently"
          pending={remove.isPending}
          onConfirm={handleConfirmDelete}
          onCancel={() => setDeleting(null)}
        >
          This permanently removes the analysis of{' '}
          <span className="font-medium">{deleting.original_filename}</span>,
          including the stored file, its findings, rules, reviews and every
          report. TrustTable will no longer recognise the file as analysed
          before. This cannot be undone.
        </ConfirmDialog>
      )}
    </section>
  )
}
