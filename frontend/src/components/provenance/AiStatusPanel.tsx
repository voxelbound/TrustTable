import { Alert } from '../ui/Alert'
import { Badge, type BadgeTone } from '../ui/Badge'
import { useAiStatus } from '../../features/workspace/api'

const STATE_BADGE: Record<
  'disabled' | 'ready' | 'unavailable',
  { tone: BadgeTone; label: string }
> = {
  disabled: { tone: 'neutral', label: 'AI assistance: off' },
  ready: { tone: 'success', label: 'AI assistance: on and ready' },
  unavailable: { tone: 'warning', label: 'AI assistance: on, not reachable' },
}

/** Local AI status for the Workspace and the Configure step (`UX-02`,
 * `docs/decision-log.md` D-068, `docs/ui-specification.md` §12.8).
 *
 * Reflects what the server found (`GET /ai/status`): whether AI assistance is
 * on, whether the runtime answered a short probe, and which model is named.
 * It replaces the former unconditional "AI is disabled" sentence, which was
 * untrue whenever a runtime was configured. Every string comes from the
 * server's fixed vocabulary; no address or path is ever available to show.
 * The text states what AI adds and that the deterministic result does not
 * depend on it. */
export function AiStatusPanel() {
  const status = useAiStatus()

  return (
    <section
      aria-labelledby="ai-status-heading"
      className="rounded border border-slate-200 p-4 dark:border-slate-800"
    >
      <h2
        id="ai-status-heading"
        className="text-base font-medium text-slate-900 dark:text-slate-100"
      >
        Local AI and privacy
      </h2>

      {status.isPending && (
        <p
          role="status"
          className="mt-2 text-sm text-slate-600 dark:text-slate-400"
        >
          Checking the Local AI status…
        </p>
      )}

      {status.isError && (
        <div className="mt-2">
          <Alert variant="warning" title="Local AI status is not available">
            The status could not be read right now. The deterministic checks do
            not depend on AI and are unaffected.
          </Alert>
        </div>
      )}

      {status.isSuccess && (
        <div className="mt-2 flex flex-col gap-2 text-sm text-slate-700 dark:text-slate-300">
          <p>
            <Badge tone={STATE_BADGE[status.data.state].tone}>
              {STATE_BADGE[status.data.state].label}
            </Badge>
          </p>
          {status.data.runtime_label !== null && (
            <p>
              Runtime: {status.data.runtime_label}
              {status.data.model_label !== null
                ? ` · Model: ${status.data.model_label}`
                : ''}
            </p>
          )}
          <p>{status.data.summary}</p>
        </div>
      )}
    </section>
  )
}
