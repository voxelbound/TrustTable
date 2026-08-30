import { Badge, type BadgeTone } from '../ui/Badge'

/** Exact wording from `docs/product-requirements.md` §9, keyed by
 * `TrustLabel`'s four enum values (`risk/scoring.py`, confirmed by
 * direct read 2026-08-30). */
const LABEL_TEXT: Record<string, string> = {
  high_confidence: 'High confidence',
  usable_with_caution: 'Usable with caution',
  material_quality_concerns: 'Material quality concerns',
  not_reliable_for_decision_making: 'Not reliable for decision-making',
}

const LABEL_TONE: Record<string, BadgeTone> = {
  high_confidence: 'success',
  usable_with_caution: 'info',
  material_quality_concerns: 'warning',
  not_reliable_for_decision_making: 'danger',
}

export interface TrustAssessmentData {
  label: string
  score: number
  finding_count: number
  highest_priority_score: number | null
}

export interface TrustAssessmentProps {
  assessment: TrustAssessmentData | null
}

/** Domain component (`docs/ui-specification.md` §5). Renders the
 * dataset's overall trust label and score — text carries the meaning,
 * color is a secondary cue only (§10). */
export function TrustAssessment({ assessment }: TrustAssessmentProps) {
  if (!assessment) {
    return (
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Trust assessment is not available yet.
      </p>
    )
  }

  const labelText = LABEL_TEXT[assessment.label] ?? assessment.label
  const tone = LABEL_TONE[assessment.label] ?? 'neutral'

  return (
    <section aria-label="Trust assessment" className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <Badge tone={tone}>{labelText}</Badge>
        <span className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
          {Math.round(assessment.score)}
          <span className="text-sm font-normal text-slate-500 dark:text-slate-400">
            {' '}
            / 100
          </span>
        </span>
      </div>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        {assessment.finding_count} finding
        {assessment.finding_count === 1 ? '' : 's'} identified.
      </p>
    </section>
  )
}
