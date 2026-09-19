import type { AiProvenanceResponse } from '../../api'
import {
  explanationCallStatusLabel,
  formatAiIdentity,
  type AiCallStatus,
} from './aiProvenanceLabels'

export interface AiProvenanceProps {
  /** `FindingExplanationResponse.provenance`. */
  provenance: string
  /** `FindingExplanationResponse.ai_provenance` — present only when an
   * accepted AI interpretation produced the analysis. */
  aiProvenance: AiProvenanceResponse | null
  /** `FindingExplanationResponse.ai_call_status`. */
  aiCallStatus: AiCallStatus
}

/** One line saying where the four analysis sections came from: an accepted
 * AI interpretation (with its human-readable identity) or TrustTable's
 * built-in guidance (with, when relevant, why no AI result is shown). */
export function AiProvenance({
  provenance,
  aiProvenance,
  aiCallStatus,
}: AiProvenanceProps) {
  if (provenance === 'ai_interpretation') {
    return (
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        AI interpretation
        {aiProvenance ? ` — ${formatAiIdentity(aiProvenance)}` : null}
      </p>
    )
  }
  const status = explanationCallStatusLabel(aiCallStatus)
  return (
    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
      Built-in TrustTable guidance (no AI)
      {status ? ` — ${status}` : null}
    </p>
  )
}
