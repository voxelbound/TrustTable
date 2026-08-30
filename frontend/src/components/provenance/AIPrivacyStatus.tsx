export interface SecurityExposureData {
  model_provider_enabled: boolean
  sample_transmission_enabled: boolean
}

export interface AIPrivacyStatusProps {
  /** Omitted before an analysis exists (e.g. the Start screen) — no AI
   * provider exists anywhere in the application yet (`AI-01`/`AI-02` not
   * built), so the disabled state is always accurate regardless. */
  exposure?: SecurityExposureData
}

/** Domain component (`docs/ui-specification.md` §5). Always reflects the
 * real, fixed AI-disabled state (`docs/product-requirements.md` §5.7) —
 * never a placeholder claim about a provider that does not exist. */
export function AIPrivacyStatus({ exposure }: AIPrivacyStatusProps) {
  const modelEnabled = exposure?.model_provider_enabled ?? false

  return (
    <p className="text-xs text-slate-600 dark:text-slate-400">
      {modelEnabled
        ? 'An AI model is enabled for this analysis.'
        : 'AI is disabled. All findings and scoring are produced by deterministic rules only — no dataset content is sent to any model.'}
    </p>
  )
}
