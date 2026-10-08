import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { AppShell } from '../../components/layout/AppShell'
import { CompareDatasetsPanel } from '../../components/layout/CompareDatasetsPanel'
import { AiStatusPanel } from '../../components/provenance/AiStatusPanel'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { getApiErrorCode, isApiErrorEnvelope } from '../../lib/apiError'
import { useCreateDemoAnalysis } from '../analysis/api'
import { useDiscardStagedUpload, useStageUpload } from './api'
import {
  forgetStagedReference,
  readStagedReference,
  rememberStagedReference,
} from './stagedReference'

interface UnreadableFile {
  filename: string
  messages: string[]
}

/** How long waiting files are kept, from a `STAGING_FULL` refusal's details,
 * or `null` when the body does not carry a usable number. */
function waitingMinutes(body: unknown): number | null {
  if (!isApiErrorEnvelope(body) || body.error.code !== 'STAGING_FULL') {
    return null
  }
  const minutes: unknown = body.error.details?.ttl_minutes
  return typeof minutes === 'number' && Number.isFinite(minutes) && minutes > 0
    ? minutes
    : null
}

/** The Workspace (`/`; `UX-02`, `docs/decision-log.md` D-068,
 * `docs/ui-specification.md` §4.1 and §12.2).
 *
 * Choosing a file never starts an analysis: it stages the file on the server
 * and opens the Configure step. A file that cannot be read at all is not
 * stored; the reasons are listed here so another file can be chosen. The sales
 * demo is a separate, explicitly labelled action. File names and messages
 * come from the server and are shown as plain text only. */
export function WorkspaceRoute() {
  const navigate = useNavigate()
  const stage = useStageUpload()
  const discard = useDiscardStagedUpload()
  const createDemo = useCreateDemoAnalysis()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [unreadable, setUnreadable] = useState<UnreadableFile | null>(null)
  const [waitingReference, setWaitingReference] = useState<string | null>(() =>
    readStagedReference(),
  )

  const chooseFile = (file: File) => {
    setUnreadable(null)
    stage.reset()
    stage.mutate(file, {
      onSuccess: (response) => {
        if (response.staging_ref === null) {
          setUnreadable({
            filename: response.filename,
            messages: response.problems.map((problem) => problem.message),
          })
          return
        }
        rememberStagedReference(response.staging_ref)
        void navigate('/configure')
      },
      onSettled: () => {
        // Allow choosing the same file again after an error: browsers do not
        // fire `change` for an unchanged selection otherwise.
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
      },
    })
  }

  const handleFileSelected = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      chooseFile(file)
    }
  }

  const handleDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    const file = event.dataTransfer.files?.[0]
    if (file && !stage.isPending) {
      chooseFile(file)
    }
  }

  const handleDiscardWaiting = () => {
    if (waitingReference !== null) {
      discard.mutate(waitingReference)
    }
    forgetStagedReference()
    setWaitingReference(null)
  }

  const handleRunDemo = () => {
    createDemo.mutate(undefined, {
      onSuccess: (response) => {
        void navigate(`/analyses/${response.analysis.analysis_id}/overview`)
      },
    })
  }

  const minutes = stage.isError ? waitingMinutes(stage.error.body) : null
  const fullMessage =
    minutes === null
      ? null
      : `Files you have chosen but not yet analyzed are kept for up to ${minutes} minutes. Finish or discard a waiting file in another tab, or try again later.`

  return (
    <AppShell>
      <div className="flex flex-col gap-8">
        <div>
          <h1 className="text-3xl font-semibold text-slate-900 dark:text-slate-100">
            TrustTable
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Investigate a spreadsheet for data-quality and trust issues before
            you rely on it.
          </p>
        </div>

        {waitingReference !== null && (
          <Alert variant="info" title="You have a file waiting">
            <p>
              You chose a file earlier and have not analyzed it yet. Files
              waiting here are kept only briefly.
            </p>
            <div className="mt-3 flex gap-2">
              <Link
                to="/configure"
                className="rounded bg-slate-900 px-4 py-2 font-medium text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200"
              >
                Continue with it
              </Link>
              <Button variant="secondary" onClick={handleDiscardWaiting}>
                Discard it
              </Button>
            </div>
          </Alert>
        )}

        <section
          aria-labelledby="choose-heading"
          onDragOver={(event) => event.preventDefault()}
          onDrop={handleDrop}
          className="rounded border-2 border-dashed border-slate-300 p-8 text-center dark:border-slate-700"
        >
          <h2
            id="choose-heading"
            className="text-lg font-medium text-slate-900 dark:text-slate-100"
          >
            Choose data
          </h2>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            Drag and drop a spreadsheet here, or choose a file. Choosing a file
            does not start an analysis; you will review it first.
          </p>
          <div className="mt-4 flex flex-col items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx"
              aria-label="Choose a file to analyze"
              disabled={stage.isPending}
              onChange={handleFileSelected}
              className="text-sm text-slate-500"
            />
            <p
              role="status"
              className="text-xs text-slate-500 dark:text-slate-400"
            >
              {stage.isPending
                ? 'Reading the file…'
                : 'CSV and Excel (.xlsx) files. Macro-enabled workbooks (.xlsm) are not supported.'}
            </p>
          </div>

          {unreadable !== null && (
            <div className="mt-4 text-left">
              <Alert variant="error" title="TrustTable cannot read this file">
                <p>
                  The file{' '}
                  <span className="font-medium">{unreadable.filename}</span> was
                  not kept.
                </p>
                <ul className="mt-2 list-disc pl-5">
                  {unreadable.messages.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
                <p className="mt-2">Choose a different file to continue.</p>
              </Alert>
            </div>
          )}

          {stage.isError && (
            <div className="mt-4 text-left">
              <Alert
                variant="error"
                title={
                  getApiErrorCode(stage.error.body) === 'STAGING_FULL'
                    ? 'Too many files are waiting'
                    : 'Could not read the file'
                }
              >
                <p>{stage.error.message}</p>
                {fullMessage !== null && <p className="mt-2">{fullMessage}</p>}
              </Alert>
            </div>
          )}
        </section>

        <section
          aria-labelledby="demo-heading"
          className="rounded border border-slate-200 p-6 dark:border-slate-800"
        >
          <h2
            id="demo-heading"
            className="text-lg font-medium text-slate-900 dark:text-slate-100"
          >
            Try the sales demo
          </h2>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            No file needed. Pressing the button starts an analysis of a
            synthetic sales dataset with known data-quality issues straight
            away.
          </p>
          <Button
            className="mt-4"
            onClick={handleRunDemo}
            disabled={createDemo.isPending}
          >
            {createDemo.isPending ? 'Starting…' : 'Try the sales demo'}
          </Button>
          {createDemo.isError && (
            <div className="mt-4">
              <Alert variant="error" title="Could not start the demo analysis">
                {createDemo.error.message}
              </Alert>
            </div>
          )}
        </section>

        <AiStatusPanel />

        <CompareDatasetsPanel />
      </div>
    </AppShell>
  )
}
