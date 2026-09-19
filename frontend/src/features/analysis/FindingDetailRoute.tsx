import { Link, useParams } from 'react-router'
import { AiProvenance } from '../../components/provenance/AiProvenance'
import type { AiCallStatus } from '../../components/provenance/aiProvenanceLabels'
import { FindingSeverityBadge } from '../../components/provenance/FindingSeverityBadge'
import { PromptInjectionWarning } from '../../components/provenance/PromptInjectionWarning'
import {
  BusinessImpactSection,
  RemediationSection,
  ValidationRuleSection,
} from './FindingGuidanceSections'
import { RowContext } from './RowContext'
import {
  useFindingDetail,
  useFindingEvidence,
  useFindingExplanation,
} from './api'

const PROMPT_INJECTION_CATEGORY = 'ai_processing_security'
const REPRESENTATIVE_SAMPLE_TYPE = 'representative_sample'

/** The Finding detail screen (`docs/ui-specification.md` §4.7), plus the
 * dedicated Prompt-injection warning presentation (§4.8) for findings in
 * the `ai_processing_security` category (`UI-01`, extending — consumes
 * `WP-027`'s `GET .../findings/{finding_id}` and `.../evidence` routes).
 *
 * **`AI-08` (`docs/decision-log.md` D-040):** Explanation, Possible
 * business impact, Remediation and Validation rule are one coherent
 * analysis, all from the same `GET .../explanation` response — a single
 * validated AI response when one was accepted, TrustTable's deterministic
 * built-in guidance otherwise, never a placeholder. Each kind of statement
 * stays distinguishable: deterministic observation/evidence above, AI
 * interpretation (labelled with a human-readable identity, never a
 * filesystem path), evidence-backed vs. conditional impact, and a
 * *proposed* rule that is explicitly not active. "Review controls" is
 * still the disclosed not-yet-available section (`REV-01`, a later
 * backlog item).
 *
 * **`WP-065` (defect fix):** Technical metadata's former generic "AI
 * model enabled" row (sourced from `finding.security_exposure`) was
 * removed — it read as a global "was AI used" claim while, for the same
 * finding, the Explanation section above could show a genuinely
 * accepted AI interpretation, and `security_exposure` is in fact a
 * narrow, prompt-injection-specific, always-`False`-today signal (see
 * `docs/decision-log.md` D-038). The provenance line under Explanation is
 * the single accurate place this screen discloses per-request AI-call
 * status; `PromptInjectionWarning` below remains the accurate place for
 * this finding's own raw-content exposure, reworded for the same
 * reason. */
export function FindingDetailRoute() {
  const { analysisId, findingId } = useParams<{
    analysisId: string
    findingId: string
  }>()
  const detailQuery = useFindingDetail(analysisId, findingId)
  const evidenceQuery = useFindingEvidence(analysisId, findingId)
  const explanationQuery = useFindingExplanation(analysisId, findingId)

  const backLink = `/analyses/${analysisId ?? ''}/findings`

  if (
    detailQuery.isLoading ||
    evidenceQuery.isLoading ||
    explanationQuery.isLoading
  ) {
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

  if (explanationQuery.isError) {
    return (
      <div className="flex flex-col gap-4">
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {explanationQuery.error.message}
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

  const explanation = explanationQuery.data
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

      {explanation && (
        <section aria-labelledby="explanation-heading">
          <h2
            id="explanation-heading"
            className="text-xl font-semibold text-slate-900 dark:text-slate-100"
          >
            Explanation
          </h2>
          <p className="mt-1 text-sm text-slate-800 dark:text-slate-200">
            {explanation.narrative}
          </p>
          <AiProvenance
            provenance={explanation.provenance}
            aiProvenance={explanation.ai_provenance}
            aiCallStatus={explanation.ai_call_status as AiCallStatus}
          />
          {explanation.evidence_sent_to_model && (
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              This finding&apos;s evidence was sent to the model for this
              request
              {explanation.confirmed_context_sent_to_model
                ? ', along with your confirmed dataset context'
                : ''}
              . The full raw dataset is never sent.
            </p>
          )}
        </section>
      )}

      {explanation && (
        <BusinessImpactSection
          statements={explanation.business_impact}
          aiAssisted={explanation.provenance === 'ai_interpretation'}
        />
      )}

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

      {explanation && (
        <>
          <RemediationSection
            steps={explanation.remediation}
            aiAssisted={explanation.provenance === 'ai_interpretation'}
          />
          <ValidationRuleSection
            rule={explanation.validation_rule}
            aiAssisted={explanation.provenance === 'ai_interpretation'}
          />
        </>
      )}

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
        </dl>
      </section>
    </div>
  )
}
