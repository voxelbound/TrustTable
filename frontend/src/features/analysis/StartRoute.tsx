import { useNavigate } from 'react-router'
import { AIPrivacyStatus } from '../../components/provenance/AIPrivacyStatus'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { useCreateDemoAnalysis } from './api'

/** The Start screen (`docs/ui-specification.md` §4.1). Upload is
 * presented but structurally disabled — there is no backend route to
 * submit an uploaded file to yet (`WP-024`'s disclosed non-goal,
 * carried forward here as `WP-025`'s Recorded assumption 3). */
export function StartRoute() {
  const navigate = useNavigate()
  const createDemo = useCreateDemoAnalysis()

  const handleRunDemo = () => {
    createDemo.mutate(undefined, {
      onSuccess: (response) => {
        void navigate(`/analyses/${response.analysis.analysis_id}/overview`)
      },
    })
  }

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
            type="file"
            aria-label="Choose a file to upload"
            disabled
            className="text-sm text-slate-500"
          />
          <p className="text-xs text-slate-500 dark:text-slate-400">
            File upload is not available yet in this preview. Try the sales demo
            below instead.
          </p>
        </div>
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
