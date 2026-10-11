import { Link } from 'react-router'
import type {
  AiConnectionTestResponse,
  AiReadinessResponse,
  ReadinessCheckResponse,
} from '../../api'
import { AppShell } from '../../components/layout/AppShell'
import { Alert, type AlertVariant } from '../../components/ui/Alert'
import { Badge, type BadgeTone } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { StateNote } from '../../components/ui/StateNote'
import { useAiReadiness, useConnectionTest } from './api'

const HEADING = 'text-xl font-semibold text-slate-900 dark:text-slate-100'
const BODY = 'text-sm text-slate-700 dark:text-slate-300'
const LINK = 'font-medium text-slate-900 underline dark:text-slate-100'

const STATE_BADGE: Record<
  ReadinessCheckResponse['state'],
  { tone: BadgeTone; label: string }
> = {
  done: { tone: 'success', label: 'Done' },
  todo: { tone: 'warning', label: 'To do' },
  attention: { tone: 'warning', label: 'Needs attention' },
  not_checked: { tone: 'neutral', label: 'Not checked yet' },
}

const OUTCOME_VARIANT: Record<
  AiConnectionTestResponse['outcome'],
  AlertVariant
> = {
  reachable: 'success',
  not_reachable: 'warning',
  assistance_off: 'info',
  no_runtime: 'info',
  not_local: 'info',
  busy: 'info',
  too_soon: 'info',
}

const OUTCOME_TITLE: Record<AiConnectionTestResponse['outcome'], string> = {
  reachable: 'The runtime answered',
  not_reachable: 'The runtime did not answer',
  assistance_off: 'Nothing was tested',
  no_runtime: 'Nothing was tested',
  not_local: 'Nothing was tested',
  busy: 'Nothing was tested',
  too_soon: 'Nothing was tested',
}

/** One sentence that sums up the checklist without claiming more than it
 * checked: even when every step is done, the model itself is not tested. */
function Summary({ readiness }: { readiness: AiReadinessResponse }) {
  if (readiness.ready) {
    return (
      <p className={BODY}>
        Every step below is done. This shows that a runtime on this machine
        answers a short check. It does not test the model or the quality of what
        it writes.
      </p>
    )
  }
  // A step to do means AI assistance is unavailable right now: it is off, no
  // runtime is named or usable, or the runtime did not answer. A step that only
  // needs attention (for example a location that cannot be confirmed) proves
  // nothing failed, so it is never described as AI being unavailable. The
  // server's own sentence says what to do, so it is shown as written.
  const todo = readiness.checks.find((check) => check.state === 'todo')
  if (todo) {
    return (
      <p className={BODY}>
        AI assistance is not available yet. {todo.detail} Everything else in
        TrustTable works with the built-in checks alone.
      </p>
    )
  }
  const attention = readiness.checks.find(
    (check) => check.state === 'attention',
  )
  return (
    <p className={BODY}>
      Local AI readiness is not fully confirmed.
      {attention ? ` ${attention.detail}` : ''} This is not a failure: AI
      assistance may still work, and everything else in TrustTable works with
      the built-in checks alone.
    </p>
  )
}

function Checklist({ readiness }: { readiness: AiReadinessResponse }) {
  return (
    <ol className="mt-3 flex flex-col gap-3">
      {readiness.checks.map((check) => (
        <li
          key={check.key}
          className="rounded border border-slate-200 p-3 dark:border-slate-800"
        >
          <p className="flex flex-wrap items-center gap-2 font-medium text-slate-900 dark:text-slate-100">
            {check.title}
            <Badge tone={STATE_BADGE[check.state].tone}>
              {STATE_BADGE[check.state].label}
            </Badge>
          </p>
          <p className={`${BODY} mt-1`}>{check.detail}</p>
        </li>
      ))}
    </ol>
  )
}

function ConnectionTest() {
  const test = useConnectionTest()

  return (
    <section aria-labelledby="local-ai-test-heading">
      <h2 id="local-ai-test-heading" className={HEADING}>
        Test the connection
      </h2>
      <p className={`${BODY} mt-2`}>
        This checks once whether the AI runtime this installation names, on this
        machine, answers a short check. It sends no data from your files and
        asks the model for nothing. You cannot choose what is tested.
      </p>
      <div className="mt-3">
        <Button disabled={test.isPending} onClick={() => test.mutate()}>
          Test connection
        </Button>
      </div>
      {test.isPending && (
        <p role="status" className={`${BODY} mt-3`}>
          Testing the connection…
        </p>
      )}
      {test.isError && (
        <div className="mt-3">
          <Alert variant="error" title="The test could not be run">
            {test.error.message} Nothing was changed.
          </Alert>
        </div>
      )}
      {test.isSuccess && (
        <div className="mt-3">
          <Alert
            variant={OUTCOME_VARIANT[test.data.outcome]}
            title={OUTCOME_TITLE[test.data.outcome]}
          >
            {test.data.message}
            {test.data.retry_after_seconds !== null &&
              ` Try again in about ${test.data.retry_after_seconds} seconds.`}
          </Alert>
        </div>
      )}
    </section>
  )
}

/** The Local AI screen (`UX-09`, D-078; `docs/ui-specification.md` §12.8). It
 * shows only what the server verified, tests only the runtime this
 * installation is configured to use, and says plainly that TrustTable does not
 * download, install, start or configure anything. */
export function LocalAiRoute() {
  const readiness = useAiReadiness()

  return (
    <AppShell>
      <div className="flex flex-col gap-8">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
            Local AI
          </h1>
          <p className={`${BODY} mt-2`}>
            AI assistance is optional. It adds an explanation beside a finding
            when a model on this machine is ready. The checks, the findings, the
            trust assessment and the built-in guidance work without it and never
            wait for it. Nothing is sent off this machine.
          </p>
        </div>

        <section aria-labelledby="local-ai-ready-heading">
          <h2 id="local-ai-ready-heading" className={HEADING}>
            Is it ready?
          </h2>
          {readiness.isLoading ? (
            <StateNote kind="loading">Checking Local AI…</StateNote>
          ) : readiness.isError ? (
            <div className="mt-3">
              <Alert variant="warning" title="Local AI could not be checked">
                {readiness.error.message} The deterministic checks do not depend
                on AI and are unaffected.
              </Alert>
            </div>
          ) : readiness.data ? (
            <div className="mt-2">
              <Summary readiness={readiness.data} />
              {readiness.data.model_label && (
                <p className={`${BODY} mt-2`}>
                  Model named: {readiness.data.model_label}
                  {readiness.data.runtime_label
                    ? ` · Runtime: ${readiness.data.runtime_label}`
                    : ''}
                </p>
              )}
              <Checklist readiness={readiness.data} />
            </div>
          ) : null}
        </section>

        <ConnectionTest />

        <section aria-labelledby="local-ai-setup-heading">
          <h2 id="local-ai-setup-heading" className={HEADING}>
            Setting it up
          </h2>
          <div className={`${BODY} mt-2 flex flex-col gap-2`}>
            <p>
              TrustTable does not download, install, start or configure an AI
              runtime or a model, and it does not browse for models. Setting one
              up happens outside TrustTable, by whoever looks after this
              installation.
            </p>
            <p>
              Once a runtime is running on this machine and this installation
              names it, turn on AI assistance in{' '}
              <Link to="/settings" className={LINK}>
                Settings
              </Link>
              , then return here and test the connection. The runtime address
              and model this installation uses are shown in Settings when
              Advanced mode is on.
            </p>
            <p>
              A runtime that is not on this machine is never used by the switch
              in Settings.
            </p>
          </div>
        </section>
      </div>
    </AppShell>
  )
}
