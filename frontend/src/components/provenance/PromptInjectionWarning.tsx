import { Alert } from '../ui/Alert'

export interface PromptInjectionWarningColumn {
  original_name: string
}

export interface PromptInjectionWarningExposure {
  model_provider_enabled: boolean
  sample_transmission_enabled: boolean
}

export interface PromptInjectionWarningProps {
  /** Columns the underlying finding names as affected
   * (`FindingDetailResponse.affected_columns`). */
  affectedColumns: readonly PromptInjectionWarningColumn[]
  /** The matching `security_pattern` evidence items' own
   * `display_safe_summary` text — the only per-value description the
   * backend exposes today. `WP-027` deliberately does not expose the raw
   * flagged substring (`structured_payload.truncated_sample_prefix`),
   * pending a future redaction package (`PRIV-01`), so this component
   * never claims to show a raw "sample" of dataset content. */
  evidenceSummaries: readonly string[]
  securityExposure: PromptInjectionWarningExposure
}

/** The dedicated Prompt-injection warning presentation
 * (`docs/ui-specification.md` §4.8). Renders only already-safe,
 * pre-computed text (`display_safe_summary`) — never a raw dataset
 * value — and never asserts malicious intent as fact (§4.8's own
 * constraint).
 *
 * **Scope note (`WP-065`, defect fix; `docs/decision-log.md` D-038):**
 * every field below (`securityExposure`, "sent to a model", "rejected-
 * output status") describes only whether *this finding's own flagged
 * raw dataset value* was sent to a model as part of the deterministic
 * detection pipeline — it is permanently "No" today because no
 * detector ever does this. It is not, and must never be read as, a
 * general "was AI used for this analysis" claim: a separate, optional,
 * per-request AI explanation (this screen's own "Explanation" section,
 * `AI-05`/`UI-02`) can independently call a real configured provider
 * for the very same finding, using only bounded evidence — never this
 * flagged raw value. The copy below is written to keep that scope
 * explicit rather than implying AI is disabled altogether. */
export function PromptInjectionWarning({
  affectedColumns,
  evidenceSummaries,
  securityExposure,
}: PromptInjectionWarningProps) {
  const sentToModel = securityExposure.sample_transmission_enabled

  return (
    <Alert
      variant="warning"
      title="Potential prompt-injection content detected"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-amber-800 dark:text-amber-300">
        Category: AI processing security
      </p>

      <div className="mt-3">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Affected field
          {affectedColumns.length === 1 ? '' : 's'}
        </h3>
        {affectedColumns.length === 0 ? (
          <p className="mt-1 text-sm">No affected column was reported.</p>
        ) : (
          <ul className="mt-1 list-inside list-disc text-sm">
            {affectedColumns.map((column) => (
              <li key={column.original_name}>{column.original_name}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-3">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          What was found
        </h3>
        {evidenceSummaries.length === 0 ? (
          <p className="mt-1 text-sm">
            No further description is available for this finding.
          </p>
        ) : (
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {evidenceSummaries.map((summary) => (
              <li key={summary}>{summary}</li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-xs text-amber-800 dark:text-amber-300">
          Only a redaction-safe description is shown here, never the raw dataset
          value.
        </p>
      </div>

      <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="font-medium">This flagged content sent to a model</dt>
        <dd>{sentToModel ? 'Yes, for this analysis' : 'No'}</dd>
        <dt className="font-medium">Where a model would run, if sent</dt>
        <dd>
          {securityExposure.model_provider_enabled
            ? 'A configured AI model'
            : 'Not applicable for this exposure path'}
        </dd>
        <dt className="font-medium">
          This flagged content&apos;s own rejected-output status
        </dt>
        <dd>
          Not applicable — this flagged content is never itself sent to any
          model by the deterministic detection pipeline, independent of whether
          an AI provider is configured elsewhere for other features (see the
          Explanation section above, when present).
        </dd>
      </dl>

      <div className="mt-3">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Protections in place
        </h3>
        <ul className="mt-1 list-inside list-disc text-sm">
          <li>
            Dataset content is only ever placed in an isolated, clearly-labeled
            untrusted-data section of any model prompt.
          </li>
          <li>Sample sending to a model is disabled by default.</li>
          <li>
            Deterministic findings and the risk score cannot be removed or
            altered by AI interpretation.
          </li>
          <li>
            Any model output would be schema-validated against evidence and
            column allow-lists before use.
          </li>
          <li>
            A model response that calls the dataset perfect or tells you to
            disregard findings is rejected, and the deterministic explanation is
            shown instead.
          </li>
        </ul>
      </div>

      <p className="mt-3 text-sm">
        This does not confirm malicious intent. It flags content that matches
        patterns commonly used in prompt-injection attempts so it can be
        reviewed, regardless of whether any AI feature is currently configured.
      </p>
    </Alert>
  )
}
