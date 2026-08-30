import { Link, useParams } from 'react-router'
import { FindingSeverityBadge } from '../../components/provenance/FindingSeverityBadge'
import { TrustAssessment } from '../../components/provenance/TrustAssessment'
import { countBySeverity, sortFindingsByPriority } from '../../domain/finding'
import { useAnalysisFindings, useAnalysisResource } from './api'

/** The Overview screen (`docs/ui-specification.md` §4.5). Section order
 * matches the specification exactly: trust assessment, top three
 * findings, immediate actions, remaining-finding summary, dataset
 * summary, technical links. "Immediate actions" and "technical links"
 * are disclosed placeholders — see `WP-025`'s Non-goals (`REM-01`
 * remediation content and the `/technical` route do not exist yet). */
export function OverviewRoute() {
  const { analysisId } = useParams<{ analysisId: string }>()
  const resourceQuery = useAnalysisResource(analysisId)
  const findingsQuery = useAnalysisFindings(analysisId)

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

  const findings = findingsQuery.data?.items ?? []
  const topFindings = sortFindingsByPriority(findings).slice(0, 3)
  const severityCounts = countBySeverity(findings)
  const dataset = resourceQuery.data?.dataset

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="trust-heading">
        <h2
          id="trust-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Trust assessment
        </h2>
        <div className="mt-2">
          <TrustAssessment
            assessment={resourceQuery.data?.trust_assessment ?? null}
          />
        </div>
      </section>

      <section aria-labelledby="top-findings-heading">
        <h2
          id="top-findings-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Top findings
        </h2>
        {topFindings.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            No findings were identified.
          </p>
        ) : (
          <ul className="mt-2 flex flex-col gap-3">
            {topFindings.map((finding) => (
              <li
                key={`${finding.detector_id}-${finding.calculated_observation}`}
                className="rounded border border-slate-200 p-3 dark:border-slate-800"
              >
                <div className="flex items-center gap-2">
                  <FindingSeverityBadge severity={finding.severity} />
                  <span className="text-sm text-slate-500 dark:text-slate-400">
                    {finding.category}
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

      <section aria-labelledby="actions-heading">
        <h2
          id="actions-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Immediate actions
        </h2>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Recommended actions are coming soon.
        </p>
      </section>

      <section aria-labelledby="remaining-findings-heading">
        <h2
          id="remaining-findings-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          All findings
        </h2>
        {Object.keys(severityCounts).length === 0 ? (
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            No findings were identified.
          </p>
        ) : (
          <ul className="mt-2 flex flex-wrap gap-3">
            {Object.entries(severityCounts).map(([severity, count]) => (
              <li key={severity} className="flex items-center gap-1">
                <FindingSeverityBadge severity={severity} />
                <span className="text-sm text-slate-600 dark:text-slate-400">
                  × {count}
                </span>
              </li>
            ))}
          </ul>
        )}
        <Link
          to={`/analyses/${analysisId ?? ''}/findings`}
          className="mt-3 inline-block text-sm font-medium text-slate-900 underline dark:text-slate-100"
        >
          View all findings
        </Link>
      </section>

      <section aria-labelledby="dataset-heading">
        <h2
          id="dataset-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Dataset summary
        </h2>
        {dataset && (
          <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm text-slate-700 dark:text-slate-300">
            <dt className="font-medium">File name</dt>
            <dd>{dataset.original_filename}</dd>
            <dt className="font-medium">Format</dt>
            <dd>{dataset.format.toUpperCase()}</dd>
            <dt className="font-medium">Size</dt>
            <dd>{dataset.byte_size.toLocaleString()} bytes</dd>
          </dl>
        )}
      </section>

      <section aria-labelledby="technical-heading">
        <h2
          id="technical-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Technical details
        </h2>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Technical details are coming soon.
        </p>
      </section>
    </div>
  )
}
