import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate } from 'react-router'
import { AppShell } from '../../components/layout/AppShell'
import { AiStatusPanel } from '../../components/provenance/AiStatusPanel'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { getApiErrorCode, getNotRunnableProblems } from '../../lib/apiError'
import {
  useDiscardStagedUpload,
  useRunStagedUpload,
  useStagedUpload,
} from './api'
import { forgetStagedReference, readStagedReference } from './stagedReference'

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

function formatKeptUntil(expiresAt: string | null | undefined): string | null {
  if (!expiresAt) {
    return null
  }
  const moment = new Date(expiresAt)
  if (Number.isNaN(moment.getTime())) {
    return null
  }
  return moment.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const STEPS = ['Choose data', 'Configure', 'Run'] as const

/** The Configure step (`/configure`; `UX-02`, `docs/decision-log.md` D-068,
 * `docs/ui-specification.md` §4.2 and §12.2).
 *
 * Shows what the server found in the chosen file before anything is analyzed:
 * file facts, a worksheet choice for a workbook (never guessed between),
 * readability problems that block Run, notices that do not, a grouped summary
 * of what is checked, the honest Local AI status and a privacy statement. There
 * are no controls to switch checks on or off: the standard analysis always
 * runs. The staged reference is read from tab-scoped storage, never from the
 * address. Everything shown that came from the file or the server is plain
 * text. */
export function ConfigureRoute() {
  const navigate = useNavigate()
  const [reference] = useState(() => readStagedReference())
  const [chosenWorksheet, setChosenWorksheet] = useState<string | null>(null)
  const staged = useStagedUpload(reference, chosenWorksheet)
  const run = useRunStagedUpload()
  const discard = useDiscardStagedUpload()
  const headingRef = useRef<HTMLHeadingElement>(null)

  const unavailable =
    (staged.isError &&
      getApiErrorCode(staged.error.body) === 'STAGED_UPLOAD_UNAVAILABLE') ||
    (run.isError &&
      getApiErrorCode(run.error.body) === 'STAGED_UPLOAD_UNAVAILABLE')

  useEffect(() => {
    if (unavailable) {
      forgetStagedReference()
    }
  }, [unavailable])

  useEffect(() => {
    headingRef.current?.focus()
  }, [staged.isSuccess, unavailable])

  if (reference === null) {
    return <Navigate to="/" replace />
  }

  const data = staged.data
  const selectedWorksheet = chosenWorksheet ?? data?.selected_worksheet ?? null
  const refreshing = staged.isFetching
  const canRun =
    data !== undefined && data.can_run && !refreshing && !run.isPending

  const handleRun = () => {
    run.mutate(
      { reference, worksheet: selectedWorksheet },
      {
        onSuccess: (response) => {
          forgetStagedReference()
          void navigate(`/analyses/${response.analysis.analysis_id}/overview`)
        },
      },
    )
  }

  const handleChooseDifferent = () => {
    discard.mutate(reference)
    forgetStagedReference()
    void navigate('/')
  }

  if (unavailable) {
    return (
      <AppShell>
        <div className="flex flex-col gap-4">
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="text-2xl font-semibold text-slate-900 dark:text-slate-100"
          >
            Your file is no longer available
          </h1>
          <Alert variant="warning" title="This file is no longer available">
            Files you choose are kept only briefly. They are deleted once they
            are analyzed or discarded, or after they expire. Choose the file
            again to continue.
          </Alert>
          <div>
            <Button onClick={() => void navigate('/')}>Choose a file</Button>
          </div>
        </div>
      </AppShell>
    )
  }

  const keptUntil = formatKeptUntil(data?.expires_at)
  const notRunnable = run.isError
    ? getNotRunnableProblems(run.error.body)
    : null

  return (
    <AppShell>
      <div className="flex flex-col gap-8">
        <div>
          <ol
            aria-label="Steps"
            className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500 dark:text-slate-400"
          >
            {STEPS.map((step) => (
              <li
                key={step}
                aria-current={step === 'Configure' ? 'step' : undefined}
                className={
                  step === 'Configure'
                    ? 'font-semibold text-slate-900 dark:text-slate-100'
                    : undefined
                }
              >
                {step}
              </li>
            ))}
          </ol>
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="mt-2 text-2xl font-semibold text-slate-900 dark:text-slate-100"
          >
            Review your file
          </h1>
          <p className="mt-1 text-slate-600 dark:text-slate-400">
            Nothing has been analyzed yet. Check the details below, then run the
            analysis.
          </p>
        </div>

        {staged.isPending && (
          <p
            role="status"
            className="text-sm text-slate-600 dark:text-slate-400"
          >
            Reading your file…
          </p>
        )}

        {staged.isError && !unavailable && (
          <Alert variant="error" title="Could not read your file">
            {staged.error.message}
          </Alert>
        )}

        {data !== undefined && (
          <>
            <section aria-labelledby="file-heading">
              <h2
                id="file-heading"
                className="text-lg font-medium text-slate-900 dark:text-slate-100"
              >
                Your file
              </h2>
              <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
                <dt className="text-slate-500 dark:text-slate-400">
                  File name
                </dt>
                <dd className="font-medium">{data.filename}</dd>
                <dt className="text-slate-500 dark:text-slate-400">Type</dt>
                <dd>
                  {data.format === 'xlsx' ? 'Excel workbook' : 'CSV file'}
                </dd>
                <dt className="text-slate-500 dark:text-slate-400">Size</dt>
                <dd>{formatBytes(data.byte_size)}</dd>
                {data.shape !== null && data.shape !== undefined && (
                  <>
                    <dt className="text-slate-500 dark:text-slate-400">Rows</dt>
                    <dd>{data.shape.row_count.toLocaleString()}</dd>
                    <dt className="text-slate-500 dark:text-slate-400">
                      Columns
                    </dt>
                    <dd>{data.shape.column_count.toLocaleString()}</dd>
                  </>
                )}
              </dl>
              {keptUntil !== null && (
                <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                  This copy is kept until {keptUntil} and is then deleted.
                </p>
              )}
            </section>

            {data.worksheets !== null && data.worksheets !== undefined && (
              <fieldset className="rounded border border-slate-200 p-4 dark:border-slate-700">
                <legend className="px-1 text-sm font-medium text-slate-900 dark:text-slate-100">
                  Which worksheet should be analyzed?
                </legend>
                <div className="mt-2 flex flex-col gap-2">
                  {data.worksheets.map((sheet) => (
                    <label
                      key={sheet.name}
                      className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300"
                    >
                      <input
                        type="radio"
                        name="worksheet"
                        value={sheet.name}
                        checked={selectedWorksheet === sheet.name}
                        onChange={() => setChosenWorksheet(sheet.name)}
                        disabled={run.isPending}
                      />
                      <span>
                        {sheet.name}
                        {sheet.visible ? '' : ' (hidden in the workbook)'}
                      </span>
                    </label>
                  ))}
                </div>
                {selectedWorksheet === null && (
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                    This workbook has more than one visible worksheet, so you
                    need to choose one.
                  </p>
                )}
              </fieldset>
            )}

            {refreshing && !staged.isPending && (
              <p
                role="status"
                className="text-sm text-slate-600 dark:text-slate-400"
              >
                Reading the worksheet…
              </p>
            )}

            {data.problems.length > 0 && (
              <Alert
                variant="error"
                title="This file cannot be analyzed as it is"
              >
                <ul className="list-disc pl-5">
                  {data.problems.map((problem) => (
                    <li key={problem.code}>{problem.message}</li>
                  ))}
                </ul>
              </Alert>
            )}

            {data.notices.length > 0 && (
              <Alert variant="info" title="Worth knowing before you run">
                <ul className="list-disc pl-5">
                  {data.notices.map((notice) => (
                    <li key={notice.code}>{notice.message}</li>
                  ))}
                </ul>
              </Alert>
            )}

            <section aria-labelledby="checks-heading">
              <h2
                id="checks-heading"
                className="text-lg font-medium text-slate-900 dark:text-slate-100"
              >
                What TrustTable will check
              </h2>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                TrustTable always runs the full standard analysis. There is
                nothing to switch on or off, and a trust assessment means all of
                these were checked.
              </p>
              <ul className="mt-2 list-disc pl-5 text-sm text-slate-700 dark:text-slate-300">
                {data.checks.map((group) => (
                  <li key={group.title}>{group.title}</li>
                ))}
              </ul>
              <details className="mt-2 text-sm text-slate-700 dark:text-slate-300">
                <summary className="cursor-pointer">
                  What each group looks for
                </summary>
                <dl className="mt-2 flex flex-col gap-2">
                  {data.checks.map((group) => (
                    <div key={group.title}>
                      <dt className="font-medium">{group.title}</dt>
                      <dd>{group.description}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            </section>
          </>
        )}

        <AiStatusPanel />

        <section
          aria-labelledby="privacy-heading"
          className="rounded border border-slate-200 p-4 dark:border-slate-800"
        >
          <h2
            id="privacy-heading"
            className="text-base font-medium text-slate-900 dark:text-slate-100"
          >
            Privacy
          </h2>
          <p className="mt-2 text-sm text-slate-700 dark:text-slate-300">
            Your file stays on this computer. The temporary copy you chose is
            deleted when you run the analysis, when you discard it, or when it
            expires. Running the analysis keeps the file with that analysis,
            also on this computer, until you delete the analysis.
          </p>
        </section>

        {run.isError && !unavailable && (
          <Alert variant="error" title="The analysis was not started">
            {notRunnable !== null ? (
              <ul className="list-disc pl-5">
                {notRunnable.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            ) : (
              <p>{run.error.message}</p>
            )}
          </Alert>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={handleRun} disabled={!canRun}>
            {run.isPending ? 'Starting…' : 'Run analysis'}
          </Button>
          <Button
            variant="secondary"
            onClick={handleChooseDifferent}
            disabled={run.isPending}
          >
            Choose a different file
          </Button>
        </div>
      </div>
    </AppShell>
  )
}
