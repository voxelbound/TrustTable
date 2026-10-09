import { Progress } from '../ui/Progress'
import { ANALYSIS_STAGE_MESSAGE, ANALYSIS_STAGES } from './analysisStages'

export interface AnalysisStageProgressProps {
  /** A non-terminal `AnalysisState` value. Terminal states
   * (`completed`/`failed`/`cancelled`) are rendered by the caller, not
   * this component. */
  state: string
}

/** Domain component (`docs/ui-specification.md` §5, §12.3). Wraps the
 * named-stage `Progress` primitive in a polite live region so stage
 * changes are announced to assistive technology (§4.3/§10).
 *
 * These stages are the deterministic analysis, and "results ready" means
 * that result is ready. Optional AI work is separate: it is prepared per
 * finding on request and never delays or is part of these stages. No time
 * estimate is shown because none is measured. */
export function AnalysisStageProgress({ state }: AnalysisStageProgressProps) {
  const message = ANALYSIS_STAGE_MESSAGE[state] ?? 'Your analysis is running.'

  return (
    <div className="flex flex-col gap-4">
      <div role="status" aria-live="polite" className="flex flex-col gap-4">
        <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
          {message}
        </p>
        <Progress
          steps={ANALYSIS_STAGES}
          currentStepId={state}
          label="Analysis progress"
        />
      </div>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Your results are ready when these steps finish. AI explanations are
        optional, are prepared separately for each finding you ask about, and
        never delay your results.
      </p>
    </div>
  )
}
