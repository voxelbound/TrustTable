import { useState } from 'react'
import { useParams } from 'react-router'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import type { ReportOptionsModel, ReportResponse } from '../../api'
import { useCreateReport, useDownloadReport, useReports } from './api'

interface OptionField {
  key: keyof ReportOptionsModel
  label: string
  hint: string
}

const OPTION_FIELDS: OptionField[] = [
  {
    key: 'include_dismissed',
    label: 'Include dismissed findings',
    hint: 'Adds findings a reviewer dismissed, with their reasons.',
  },
  {
    key: 'include_technical_appendix',
    label: 'Include technical appendix',
    hint: 'Adds detector versions, confidence, evidence identifiers and rule provenance.',
  },
  {
    key: 'include_bounded_examples',
    label: 'Include bounded examples',
    hint: 'Adds observation text and up to five affected row numbers per finding. Examples may quote values from your dataset.',
  },
]

const NO_OPTIONS: ReportOptionsModel = {
  include_dismissed: false,
  include_technical_appendix: false,
  include_bounded_examples: false,
}

function describeOptions(options: ReportOptionsModel): string {
  const chosen = OPTION_FIELDS.filter((field) => options[field.key]).map(
    (field) => field.label.replace(/^Include /, ''),
  )
  return chosen.length === 0 ? 'Default options' : chosen.join(', ')
}

/** Saves text as a Markdown file through a temporary object URL. The text
 * is never inserted into the page. */
function saveMarkdown(reportId: string, text: string) {
  const url = URL.createObjectURL(
    new Blob([text], { type: 'text/markdown;charset=utf-8' }),
  )
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `report-${reportId}.md`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/** The Report screen (`docs/ui-specification.md` §4.10; `UI-03` slice 2).
 * Generates an immutable report snapshot with explicitly chosen options
 * (all off by default), lists the stored snapshots and downloads the
 * stored Markdown of any of them. */
export function ReportRoute() {
  const { analysisId } = useParams<{ analysisId: string }>()
  const reportsQuery = useReports(analysisId)
  const createMutation = useCreateReport(analysisId)
  const downloadMutation = useDownloadReport(analysisId)
  const [options, setOptions] = useState<ReportOptionsModel>(NO_OPTIONS)
  const [downloadingId, setDownloadingId] = useState<string | null>(null)

  const handleGenerate = (event: React.FormEvent) => {
    event.preventDefault()
    createMutation.mutate(options)
  }

  const handleDownload = (report: ReportResponse) => {
    setDownloadingId(report.report_id)
    downloadMutation.mutate(report.report_id, {
      onSuccess: (text) => saveMarkdown(report.report_id, text),
      onSettled: () => setDownloadingId(null),
    })
  }

  const reports = reportsQuery.data?.reports ?? []
  const actionError = createMutation.error ?? downloadMutation.error

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="generate-report-heading">
        <h2
          id="generate-report-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Generate a report
        </h2>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          A report is a snapshot: later reviews or rule changes do not alter a
          report that has already been generated.
        </p>
        <form onSubmit={handleGenerate} className="mt-3">
          <fieldset className="flex flex-col gap-3">
            <legend className="text-sm font-medium text-slate-900 dark:text-slate-100">
              Report options
            </legend>
            {OPTION_FIELDS.map((field) => (
              <div key={field.key} className="flex items-start gap-2">
                <input
                  id={`report-option-${field.key}`}
                  type="checkbox"
                  className="mt-1"
                  checked={Boolean(options[field.key])}
                  aria-describedby={`report-option-${field.key}-hint`}
                  onChange={(event) =>
                    setOptions((current) => ({
                      ...current,
                      [field.key]: event.target.checked,
                    }))
                  }
                />
                <div>
                  <label
                    htmlFor={`report-option-${field.key}`}
                    className="text-sm text-slate-900 dark:text-slate-100"
                  >
                    {field.label}
                  </label>
                  <p
                    id={`report-option-${field.key}-hint`}
                    className="text-xs text-slate-600 dark:text-slate-400"
                  >
                    {field.hint}
                  </p>
                </div>
              </div>
            ))}
          </fieldset>
          <Button
            type="submit"
            className="mt-4"
            disabled={createMutation.isPending}
          >
            {createMutation.isPending ? 'Generating…' : 'Generate report'}
          </Button>
        </form>
      </section>

      {actionError && (
        <Alert variant="error" title="That action could not be completed">
          {actionError.message}
        </Alert>
      )}

      <section aria-labelledby="reports-heading">
        <h2
          id="reports-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Generated reports
        </h2>
        {reportsQuery.isLoading ? (
          <p
            role="status"
            aria-live="polite"
            className="mt-2 text-sm text-slate-600 dark:text-slate-400"
          >
            Loading reports…
          </p>
        ) : reportsQuery.isError ? (
          <div className="mt-2">
            <Alert variant="error" title="Could not load reports">
              {reportsQuery.error.message}
            </Alert>
          </div>
        ) : reports.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            No reports have been generated for this analysis yet.
          </p>
        ) : (
          <ol className="mt-2 flex flex-col gap-3">
            {reports.map((report) => (
              <li
                key={report.report_id}
                className="rounded border border-slate-200 p-3 dark:border-slate-800"
              >
                <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                  Generated {report.generated_at}
                </p>
                <p className="text-sm text-slate-700 dark:text-slate-300">
                  {describeOptions(report.options)}
                </p>
                <p className="break-all text-xs text-slate-600 dark:text-slate-400">
                  SHA-256 {report.content_sha256}
                </p>
                <Button
                  variant="secondary"
                  className="mt-2"
                  disabled={downloadingId !== null}
                  aria-label={`Download report generated ${report.generated_at}`}
                  onClick={() => handleDownload(report)}
                >
                  {downloadingId === report.report_id
                    ? 'Downloading…'
                    : 'Download Markdown'}
                </Button>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}
