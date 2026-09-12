import { Link, useParams } from 'react-router'
import { FindingSeverityBadge } from '../../components/provenance/FindingSeverityBadge'
import { PromptInjectionWarning } from '../../components/provenance/PromptInjectionWarning'
import { RowContext } from './RowContext'
import { useFindingDetail, useFindingEvidence } from './api'

const PROMPT_INJECTION_CATEGORY = 'ai_processing_security'
const REPRESENTATIVE_SAMPLE_TYPE = 'representative_sample'

/** The Finding detail screen (`docs/ui-specification.md` §4.7), plus the
 * dedicated Prompt-injection warning presentation (§4.8) for findings in
 * the `ai_processing_security` category (`UI-01`, extending — consumes
 * `WP-027`'s `GET .../findings/{finding_id}` and `.../evidence` routes).
 *
 * "Possible business impact", "Remediation", "Validation rule", and
 * "Review controls" render the same disclosed not-yet-available pattern
 * `OverviewRoute.tsx` already established for its own unbuilt sections —
 * `REM-01`/`RULE-01`/`REV-01` are later, unimplemented backlog items;
 * the backend does not compute this content yet (`WP-027`'s own Recorded
 * assumption 4), so no placeholder value is fabricated here either. */
export function FindingDetailRoute() {
  const { analysisId, findingId } = useParams<{
    analysisId: string
    findingId: string
  }>()
  const detailQuery = useFindingDetail(analysisId, findingId)
  const evidenceQuery = useFindingEvidence(analysisId, findingId)

  const backLink = `/analyses/${analysisId ?? ''}/findings`

  if (detailQuery.isLoading || evidenceQuery.isLoading) {
    return (
      <p
        role="status"
        aria-live="polite"
        className="text-sm text-slate-600 dark:text-slate-400"
      >
        Loading finding…
      </p>
    )
  }

  if (detailQuery.isError) {
    return (
      <div className="flex flex-col gap-4">
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {detailQuery.error.message}
        </p>
        <Link
          to={backLink}
          className="text-sm font-medium text-slate-900 underline dark:text-slate-100"
        >
          Back to findings
        </Link>
      </div>
    )
  }

  if (evidenceQuery.isError) {
    return (
      <div className="flex flex-col gap-4">
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {evidenceQuery.error.message}
        </p>
        <Link
          to={backLink}
          className="text-sm font-medium text-slate-900 underline dark:text-slate-100"
        >
          Back to findings
        </Link>
      </div>
    )
  }

  const finding = detailQuery.data
  if (!finding) {
    return null
  }

  const evidenceItems = evidenceQuery.data?.items ?? []
  const representativeExamples = evidenceItems.filter(
    (item) => item.evidence_type === REPRESENTATIVE_SAMPLE_TYPE,
  )
  const otherEvidence = evidenceItems.filter(
    (item) => item.evidence_type !== REPRESENTATIVE_SAMPLE_TYPE,
  )
  const isPromptInjection = finding.category === PROMPT_INJECTION_CATEGORY

  return (
    <div className="flex flex-col gap-8">
      <Link
        to={backLink}
        className="text-sm font-medium text-slate-900 underline dark:text-slate-100"
      >
        ← Back to findings
      </Link>

      <section aria-labelledby="observation-heading">
        <div className="flex items-center gap-2">
          <FindingSeverityBadge severity={finding.severity} />
          <span className="text-sm text-slate-500 dark:text-slate-400">
            {finding.category}
          </span>
        </div>
        <h2
          id="observation-heading"
          className="mt-2 text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Observation
        </h2>
        <p className="mt-1 text-sm text-slate-800 dark:text-slate-200">
          {finding.calculated_observation}
        </p>
      </section>

      <section aria-labelledby="impact-heading">
        <h2
          id="impact-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Possible business impact
        </h2>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Not yet available — business-impact analysis is a later backlog item.
        </p>
      </section>

      {isPromptInjection ? (
        <section aria-labelledby="warning-heading">
          <h2 id="warning-heading" className="sr-only">
            Prompt-injection warning
          </h2>
          <PromptInjectionWarning
            affectedColumns={finding.affected_columns}
            evidenceSummaries={otherEvidence.map(
              (item) => item.display_safe_summary,
            )}
            securityExposure={finding.security_exposure}
          />
        </section>
      ) : (
        <section aria-labelledby="evidence-heading">
          <h2
            id="evidence-heading"
            className="text-xl font-semibold text-slate-900 dark:text-slate-100"
          >
            Evidence
          </h2>
          {otherEvidence.length === 0 ? (
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
              No evidence items were recorded for this finding.
            </p>
          ) : (
            <ul className="mt-2 flex flex-col gap-3">
              {otherEvidence.map((item) => (
                <li
                  key={item.evidence_id}
                  className="rounded border border-slate-200 p-3 text-sm dark:border-slate-800"
                >
                  <p className="text-slate-800 dark:text-slate-200">
                    {item.display_safe_summary}
                  </p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    Affected rows: {item.affected_row_count}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {representativeExamples.length > 0 && (
        <section aria-labelledby="examples-heading">
          <h2
            id="examples-heading"
            className="text-xl font-semibold text-slate-900 dark:text-slate-100"
          >
            Representative examples
          </h2>
          <ul className="mt-2 flex flex-col gap-3">
            {representativeExamples.map((item) => (
              <li
                key={item.evidence_id}
                className="rounded border border-slate-200 p-3 text-sm dark:border-slate-800"
              >
                <p className="text-slate-800 dark:text-slate-200">
                  {item.display_safe_summary}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {analysisId && (
        <RowContext
          analysisId={analysisId}
          findingId={finding.finding_id}
          affectedRowNumbers={finding.affected_row_numbers}
        />
      )}

      <section aria-labelledby="remediation-heading">
        <h2
          id="remediation-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Remediation
        </h2>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Not yet available — remediation recommendations are a later backlog
          item.
        </p>
      </section>

      <section aria-labelledby="rule-heading">
        <h2
          id="rule-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Validation rule
        </h2>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Not yet available — proposed validation rules are a later backlog
          item.
        </p>
      </section>

      <section aria-labelledby="review-heading">
        <h2
          id="review-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Review controls
        </h2>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Not yet available — persistent finding review is a later backlog item.
        </p>
      </section>

      <section aria-labelledby="technical-heading">
        <h2
          id="technical-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Technical metadata
        </h2>
        <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm text-slate-700 dark:text-slate-300">
          <dt className="font-medium">Detector</dt>
          <dd>
            {finding.detector_id} (v{finding.detector_version})
          </dd>
          <dt className="font-medium">Confidence</dt>
          <dd>{Math.round(finding.confidence * 100)}%</dd>
          <dt className="font-medium">Priority score</dt>
          <dd>{finding.priority_score}</dd>
          <dt className="font-medium">Affected rows</dt>
          <dd>{finding.affected_row_count}</dd>
          <dt className="font-medium">AI model enabled</dt>
          <dd>
            {finding.security_exposure.model_provider_enabled ? 'Yes' : 'No'}
          </dd>
        </dl>
      </section>
    </div>
  )
}
