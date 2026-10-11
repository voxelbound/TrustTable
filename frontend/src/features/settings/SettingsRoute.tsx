import { useState } from 'react'
import { Link } from 'react-router'
import type { AdvancedSettingsResponse, SettingItemResponse } from '../../api'
import { AppShell } from '../../components/layout/AppShell'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { StateNote } from '../../components/ui/StateNote'
import { getApiErrorCode } from '../../lib/apiError'
import { useAdvancedMode } from '../../lib/advancedMode'
import type { ApiCallError } from '../analysis/api'
import {
  useAdvancedSettings,
  useResetSetting,
  useSettings,
  useWriteSetting,
} from './api'

const HEADING = 'text-xl font-semibold text-slate-900 dark:text-slate-100'
const BODY = 'text-sm text-slate-700 dark:text-slate-300'
const MUTED = 'text-sm text-slate-600 dark:text-slate-400'
const LABEL = 'font-medium text-slate-900 dark:text-slate-100'

const SOURCE_TEXT: Record<SettingItemResponse['source'], string> = {
  deployment: 'Set by your installation',
  stored: 'Saved in TrustTable for this installation',
  default: 'The built-in default',
}

/** The words for a refused change. Every one says that nothing was changed
 * and that the value shown is what the server holds now. */
function describeFailure(error: ApiCallError): string {
  switch (getApiErrorCode(error.body)) {
    case 'SETTING_VERSION_CONFLICT':
      return 'This setting was changed somewhere else, so nothing was changed. The value now shown is the current one. Change it again if you still want to.'
    case 'SETTING_MANAGED_BY_INSTALLATION':
      return 'Your installation manages this setting, so nothing was changed. TrustTable cannot override it.'
    default:
      return `${error.message} Nothing was changed.`
  }
}

function Explained({
  controls,
  why,
  consequence,
}: {
  controls: string
  why: string
  consequence: string
}) {
  return (
    <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
      <dt className={LABEL}>What it controls</dt>
      <dd className={BODY}>{controls}</dd>
      <dt className={LABEL}>Why you might change it</dt>
      <dd className={BODY}>{why}</dd>
      <dt className={LABEL}>What changes</dt>
      <dd className={BODY}>{consequence}</dd>
    </dl>
  )
}

function AiAssistanceSetting({ item }: { item: SettingItemResponse }) {
  const write = useWriteSetting()
  const reset = useResetSetting()
  const [failure, setFailure] = useState<ApiCallError | null>(null)
  const busy = write.isPending || reset.isPending
  const managed = item.managed_by_installation

  const change = (value: boolean) => {
    setFailure(null)
    write.mutate(
      { key: item.key, value, expectedVersion: item.version },
      { onError: setFailure },
    )
  }
  const resetToDefault = () => {
    setFailure(null)
    reset.mutate(
      { key: item.key, expectedVersion: item.version },
      { onError: setFailure },
    )
  }

  return (
    <section aria-labelledby="setting-ai-heading">
      <h2 id="setting-ai-heading" className={HEADING}>
        AI assistance
      </h2>
      <Explained
        controls="Whether TrustTable may ask an AI model on this machine to explain a finding. The checks, the findings, the trust assessment and the built-in guidance never depend on it."
        why="Turn it on if you have set up a local model and want AI explanations beside the built-in guidance. Leave it off to use the built-in guidance only."
        consequence="When it is on and a local model is ready, bounded details about a finding you open, which the analysis already worked out, can be sent to that model on this machine. Whether example values are included is decided by your installation, not here. When it is off, nothing is sent."
      />

      <p className={`${BODY} mt-4`}>
        <span className={LABEL}>Now: </span>
        {item.value ? 'On' : 'Off'}
        <span className={MUTED}> · {SOURCE_TEXT[item.source]}</span>
      </p>
      {item.note && (
        <p role="note" className={`${BODY} mt-1`}>
          {item.note}
        </p>
      )}

      {managed ? (
        <p className={`${MUTED} mt-3`}>
          Your installation manages this setting, so it is shown here and cannot
          be changed from this screen. TrustTable never edits your
          installation’s configuration.
        </p>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className={`${BODY} flex items-center gap-2`}>
            <input
              type="checkbox"
              checked={item.value}
              disabled={busy}
              onChange={(event) => change(event.target.checked)}
            />
            Use AI assistance
          </label>
          {item.source === 'stored' && (
            <Button
              variant="secondary"
              disabled={busy}
              onClick={resetToDefault}
            >
              Reset to default (off)
            </Button>
          )}
        </div>
      )}

      {failure && (
        <div className="mt-3">
          <Alert variant="error" title="The setting was not changed">
            {describeFailure(failure)}
          </Alert>
        </div>
      )}

      <p className={`${MUTED} mt-3`}>
        To see whether a local model is ready, and to test the connection, open{' '}
        <Link to="/local-ai" className="underline">
          Local AI
        </Link>
        .
      </p>
    </section>
  )
}

function AdvancedFacts({ data }: { data: AdvancedSettingsResponse }) {
  const rows: [string, string][] = [
    ['AI provider', data.ai_provider],
    [
      'AI assistance comes from',
      SOURCE_TEXT[data.ai_assistance_source].toLowerCase(),
    ],
    ['Runtime address', data.runtime_address ?? 'Not in use'],
    ['Model', data.model_identifier ?? 'Not in use'],
    ['Timeout (seconds)', String(data.timeout_seconds)],
    ['Context window (tokens)', String(data.context_window)],
    ['Example values sent to a model', data.sample_values_sent ? 'Yes' : 'No'],
    ['Most example values per request', String(data.max_sample_values)],
  ]
  return (
    <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className={MUTED}>{label}</dt>
          <dd className={`${BODY} break-all`}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Shown only in Advanced mode, and the only place the runtime address and the
 * model are shown. The request is made only while this is rendered. */
function AdvancedSection() {
  const query = useAdvancedSettings(true)
  return (
    <section aria-labelledby="setting-runtime-heading">
      <h2 id="setting-runtime-heading" className={HEADING}>
        Runtime and model (Advanced)
      </h2>
      <p className={`${MUTED} mt-2`}>
        What this installation is configured to use for AI assistance. It is
        read-only: it is changed in your installation’s configuration, not here.
      </p>
      {query.isLoading ? (
        <StateNote kind="loading">Loading the runtime and model…</StateNote>
      ) : query.isError ? (
        <div className="mt-3">
          <Alert variant="error" title="Could not load the runtime and model">
            {query.error.message}
          </Alert>
        </div>
      ) : query.data ? (
        <AdvancedFacts data={query.data} />
      ) : null}
    </section>
  )
}

/** The Settings screen (`UX-08b`, D-077; `docs/ui-specification.md` §12.6). It
 * shows only what the server returned: nothing is assumed before a change is
 * confirmed. */
export function SettingsRoute() {
  const settings = useSettings()
  const [advanced, setAdvanced] = useAdvancedMode()
  const ai = settings.data?.settings.find((s) => s.key === 'ai_assistance')

  return (
    <AppShell>
      <div className="flex flex-col gap-8">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
            Settings
          </h1>
          <p className={`${BODY} mt-2`}>
            How TrustTable behaves on this installation, and how it is shown in
            this browser.
          </p>
        </div>

        {settings.isLoading ? (
          <StateNote kind="loading">Loading the settings…</StateNote>
        ) : settings.isError ? (
          <Alert variant="error" title="Could not load the settings">
            {settings.error.message}
          </Alert>
        ) : ai ? (
          <AiAssistanceSetting item={ai} />
        ) : (
          <StateNote kind="empty">No settings are available.</StateNote>
        )}

        <section aria-labelledby="setting-display-heading">
          <h2 id="setting-display-heading" className={HEADING}>
            Advanced mode
          </h2>
          <Explained
            controls="Whether technical detail is shown: the Technical details area of an analysis, and below, the runtime and model this installation uses."
            why="Turn it on if you need to see how a file was read, how columns were measured or which AI runtime is configured. Most people do not need it."
            consequence="Only what is shown changes. Nothing about the analysis, the findings or what is sent to a model changes, and it is not a security control. The choice is kept in this browser only."
          />
          <label className={`${BODY} mt-3 flex items-center gap-2`}>
            <input
              type="checkbox"
              checked={advanced}
              onChange={(event) => setAdvanced(event.target.checked)}
            />
            Show technical detail (Advanced mode)
          </label>
        </section>

        {advanced && <AdvancedSection />}
      </div>
    </AppShell>
  )
}
