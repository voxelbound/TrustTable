import type { AiProvenanceResponse } from '../../api'

/** `ai_call_status`'s closed set (`WP-065`, defect fix). Kept as a small
 * local union rather than importing the generated enum type, mirroring
 * this codebase's informal-typing convention for other response string
 * fields. */
export type AiCallStatus =
  | 'not_configured'
  | 'attempted_accepted'
  | 'attempted_rejected'
  | 'attempted_provider_error'

/** Describes one request's own AI-call outcome (`ai_call_status`),
 * deliberately never a claim about whether AI is used anywhere else on the
 * screen or on the analysis in general (`docs/decision-log.md` D-038). */
export function explanationCallStatusLabel(status: AiCallStatus): string {
  switch (status) {
    case 'attempted_accepted':
      return ''
    case 'attempted_rejected':
      return 'an AI attempt for this analysis did not produce a usable result'
    case 'attempted_provider_error':
      return 'an AI attempt for this analysis could not complete'
    case 'not_configured':
    default:
      return 'no AI provider is configured'
  }
}

/** A human-readable identity for the AI that produced an interpretation,
 * built only from the backend's already-derived display labels (`AI-08`,
 * `docs/decision-log.md` D-040): for example
 * `Local AI · llama.cpp · Qwen3.5 4B (Q4_K_M)`.
 *
 * Never built from the raw configured model value, which can be an
 * absolute host path: the backend does not return it, and this module
 * deliberately has no way to render it. */
export function formatAiIdentity(provenance: AiProvenanceResponse): string {
  const model = provenance.model_label
    ? provenance.quantization
      ? `${provenance.model_label} (${provenance.quantization})`
      : provenance.model_label
    : null
  return [provenance.deployment_label, provenance.runtime_label, model]
    .filter((part): part is string => Boolean(part))
    .join(' · ')
}
