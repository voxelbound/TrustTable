import { Link, useParams } from 'react-router'
import { FindingSeverityBadge } from '../../components/provenance/FindingSeverityBadge'
import { TrustAssessment } from '../../components/provenance/TrustAssessment'
import { categoryLabel } from '../../domain/dashboard'
import { sortFindingsByPriority } from '../../domain/finding'
import {
  useAnalysisFindings,
  useAnalysisResource,
  useAnalysisSummary,
} from './api'
import {
  AtAGlance,
  ColumnsWithMostFindings,
  FindingDistribution,
} from './DashboardSections'
import { ObservationsList } from './ObservationsList'

const HEADING_CLASS = 'text-xl font-semibold text-slate-900 dark:text-slate-100'

/** The Overview screen, a business-oriented dashboard (`UX-04`, D-070;
 * `docs/ui-specification.md` §4.5 and §12). Order: trust assessment, the
 * headline figures, what was found, where, the top findings, what is worth
 * knowing, the dataset, and technical details.
 *
 * Every figure here comes from the deterministic analysis. Nothing on this
 * screen waits for, or implies, an AI result. The summary figures that the
 * list responses cannot answer come from `GET .../summary`; if that request
 * fails the rest of the page still renders. */
export function OverviewRoute() {
  const { analysisId } = useParams<{ analysisId: string }>()
  const resourceQuery = useAnalysisResource(analysisId)
  const findingsQuery = useAnalysisFindings(analysisId)
  const summaryQuery = useAnalysisSummary(analysisId)

  if (resourceQuery.isLoading || findingsQuery.isLoading) {
    return (
      <p
        role="status"
        aria-live="polite"
        className="text-sm text-slate-600 dark:text-slate-400"
      >
        Loading overview…
      </p>
    )
  }

  if (resourceQuery.isError) {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-300">
        {resourceQuery.error.message}
      </p>
    )
  }

  // `null` means the request failed: an unknown result is never shown as
  // "no findings", which would read as a clean file.
  const findings = findingsQuery.isError
    ? null
    : (findingsQuery.data?.items ?? [])
  const topFindings = sortFindingsByPriority(findings ?? []).slice(0, 3)
  const dataset = resourceQuery.data?.dataset
  const summary = summaryQuery.data
  const summaryState = summaryQuery.isError
    ? 'error'
    : summaryQuery.isLoading
      ? 'loading'
      : 'ready'

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="trust-heading">
        <h2 id="trust-heading" className={HEADING_CLASS}>
          Trust assessment
        </h2>
        <div className="mt-2">
          <TrustAssessment
            assessment={resourceQuery.data?.trust_assessment ?? null}
          />
        </div>
      </section>

      <AtAGlance
        summary={summary}
        summaryState={summaryState}
        findings={findings}
      />

      <FindingDistribution
        findings={findings}
        findingsHref={
          <Link
            to={`/analyses/${analysisId ?? ''}/findings`}
            className="mt-3 inline-block text-sm font-medium text-slate-900 underline dark:text-slate-100"
          >
            View all findings
          </Link>
        }
      />

      <ColumnsWithMostFindings findings={findings} />

      <section aria-labelledby="top-findings-heading">
        <h2 id="top-findings-heading" className={HEADING_CLASS}>
          Top findings
        </h2>
        {findings === null ? (
          <p
            role="alert"
            className="mt-2 text-sm text-red-700 dark:text-red-300"
          >
            The findings could not be loaded.
          </p>
        ) : topFindings.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            No findings were identified.
          </p>
        ) : (
          <ul className="mt-2 flex flex-col gap-3">
            {topFindings.map((finding) => (
              <li
                key={finding.finding_id}
                className="rounded border border-slate-200 p-3 dark:border-slate-800"
              >
                <div className="flex items-center gap-2">
                  <FindingSeverityBadge severity={finding.severity} />
                  <span className="text-sm text-slate-500 dark:text-slate-400">
                    {categoryLabel(finding.category)}
                  </span>
                </div>
                <p className="mt-1 text-sm text-slate-800 dark:text-slate-200">
                  {finding.calculated_observation}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <ObservationsList analysisId={analysisId} />

      <section aria-labelledby="dataset-heading">
        <h2 id="dataset-heading" className={HEADING_CLASS}>
          Dataset summary
        </h2>
        {dataset && (
          <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm text-slate-700 dark:text-slate-300">
            <dt className="font-medium">File name</dt>
            <dd>{dataset.original_filename}</dd>
            <dt className="font-medium">Format</dt>
            <dd>{dataset.format.toUpperCase()}</dd>
            {dataset.selected_worksheet && (
              <>
                <dt className="font-medium">Worksheet analyzed</dt>
                <dd>{dataset.selected_worksheet}</dd>
              </>
            )}
            <dt className="font-medium">Size</dt>
            <dd>{dataset.byte_size.toLocaleString()} bytes</dd>
            {summary && (
              <>
                <dt className="font-medium">Rows</dt>
                <dd>{summary.row_count.toLocaleString()}</dd>
                <dt className="font-medium">Columns</dt>
                <dd>{summary.column_count.toLocaleString()}</dd>
              </>
            )}
          </dl>
        )}
      </section>

      <section aria-labelledby="technical-heading">
        <h2 id="technical-heading" className={HEADING_CLASS}>
          Technical details
        </h2>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          How the file was read, column profiles and the evidence behind the
          findings.
        </p>
        <div className="mt-3 flex gap-4">
          <Link
            to={`/analyses/${analysisId ?? ''}/technical`}
            className="inline-block text-sm font-medium text-slate-900 underline dark:text-slate-100"
          >
            Open technical details
          </Link>
          <Link
            to={`/analyses/${analysisId ?? ''}/context`}
            className="inline-block text-sm font-medium text-slate-900 underline dark:text-slate-100"
          >
            Review dataset context
          </Link>
        </div>
      </section>
    </div>
  )
}
