import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { AIPrivacyStatus } from '../../components/provenance/AIPrivacyStatus'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { getWorksheetChoices } from '../../lib/apiError'
import { useCreateAnalysisUpload, useCreateDemoAnalysis } from './api'

/** A workbook the API could not analyze without a worksheet choice: the
 * file is kept so the same file is sent again with the picked worksheet. */
interface PendingWorkbook {
  file: File
  worksheets: string[]
}

/** The Start screen (`docs/ui-specification.md` §4.1). Upload accepts CSV
 * (`WP-029`) and Excel `.xlsx` (`ING-03`). A workbook with several
 * worksheets is refused by the API with `WORKSHEET_REQUIRED` and the
 * worksheet names; the screen then asks which one to analyze and uploads
 * the same file again with that worksheet. The UI never guesses between
 * worksheets, and the names (which come from an untrusted file) are shown
 * only as plain text. */
export function StartRoute() {
  const navigate = useNavigate()
  const createDemo = useCreateDemoAnalysis()
  const createUpload = useCreateAnalysisUpload()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [pending, setPending] = useState<PendingWorkbook | null>(null)
  const [chosenWorksheet, setChosenWorksheet] = useState<string | null>(null)

  const handleRunDemo = () => {
    createDemo.mutate(undefined, {
      onSuccess: (response) => {
        void navigate(`/analyses/${response.analysis.analysis_id}/overview`)
      },
    })
  }

  const upload = (file: File, worksheet?: string) => {
    createUpload.mutate(
      worksheet === undefined ? { file } : { file, worksheet },
      {
        onSuccess: (response) => {
          setPending(null)
          setChosenWorksheet(null)
          void navigate(`/analyses/${response.analysis.analysis_id}/overview`)
        },
        onError: (error) => {
          const worksheets = getWorksheetChoices(error.body)
          if (worksheets !== null && worksheet === undefined) {
            setPending({ file, worksheets })
            setChosenWorksheet(null)
          }
        },
        onSettled: () => {
          // Allow re-selecting the same file after an error without a
          // page reload (browsers do not fire `change` for an unchanged
          // selection otherwise).
          if (fileInputRef.current) {
            fileInputRef.current.value = ''
          }
        },
      },
    )
  }

  const handleFileSelected = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) {
      return
    }
    setPending(null)
    setChosenWorksheet(null)
    upload(file)
  }

  const handleWorksheetSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (pending && chosenWorksheet !== null) {
      upload(pending.file, chosenWorksheet)
    }
  }

  const handleWorksheetCancel = () => {
    setPending(null)
    setChosenWorksheet(null)
    createUpload.reset()
  }

  // The worksheet chooser replaces the generic error for the one refusal it
  // resolves; every other refusal is shown as the API's own message, and
  // the chooser stays available so another worksheet can be tried.
  const showUploadError =
    createUpload.isError &&
    getWorksheetChoices(createUpload.error.body) === null

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 px-6 py-16">
      <div>
        <h1 className="text-3xl font-semibold text-slate-900 dark:text-slate-100">
          TrustTable
        </h1>
        <p className="mt-2 text-slate-600 dark:text-slate-400">
          Investigate a spreadsheet for data-quality and trust issues before you
          rely on it.
        </p>
      </div>

      <section
        aria-labelledby="upload-heading"
        className="rounded border-2 border-dashed border-slate-300 p-8 text-center dark:border-slate-700"
      >
        <h2
          id="upload-heading"
          className="text-lg font-medium text-slate-900 dark:text-slate-100"
        >
          Upload a file
        </h2>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Drag and drop a spreadsheet here, or choose a file.
        </p>
        <div className="mt-4 flex flex-col items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx"
            aria-label="Choose a file to upload"
            disabled={createUpload.isPending}
            onChange={handleFileSelected}
            className="text-sm text-slate-500"
          />
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {createUpload.isPending
              ? 'Uploading and analyzing…'
              : 'CSV and Excel (.xlsx) files. If a workbook has several worksheets you will choose which one to analyze. Macro-enabled workbooks (.xlsm) are not supported.'}
          </p>
        </div>
        {pending && (
          <form
            onSubmit={handleWorksheetSubmit}
            className="mt-6 text-left"
            aria-label="Choose a worksheet"
          >
            <fieldset className="rounded border border-slate-200 p-4 dark:border-slate-700">
              <legend className="px-1 text-sm font-medium text-slate-900 dark:text-slate-100">
                This workbook has several worksheets. Which one should be
                analyzed?
              </legend>
              <div className="mt-2 flex flex-col gap-2">
                {pending.worksheets.map((name) => (
                  <label
                    key={name}
                    className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300"
                  >
                    <input
                      type="radio"
                      name="worksheet"
                      value={name}
                      checked={chosenWorksheet === name}
                      onChange={() => setChosenWorksheet(name)}
                      disabled={createUpload.isPending}
                    />
                    <span>{name}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="mt-3 flex gap-2">
              <Button
                type="submit"
                disabled={chosenWorksheet === null || createUpload.isPending}
              >
                Analyze this worksheet
              </Button>
              <Button
                variant="secondary"
                onClick={handleWorksheetCancel}
                disabled={createUpload.isPending}
              >
                Cancel
              </Button>
            </div>
          </form>
        )}
        {showUploadError && (
          <div className="mt-4">
            <Alert variant="error" title="Could not analyze the uploaded file">
              {createUpload.error.message}
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
          Run a full analysis on a synthetic sales dataset with known
          data-quality issues — no file needed.
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

      <AIPrivacyStatus />
    </main>
  )
}
