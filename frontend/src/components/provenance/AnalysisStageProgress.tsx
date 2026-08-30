import { Progress, type ProgressStep } from '../ui/Progress'

/** The five non-terminal `AnalysisState` values, in pipeline order
 * (`analysis/service.py`, confirmed by direct read 2026-08-30). */
const STAGES: ProgressStep[] = [
  { id: 'queued', label: 'Queued' },
  { id: 'validating', label: 'Validating dataset' },
  { id: 'parsing', label: 'Parsing dataset' },
  { id: 'profiling', label: 'Profiling columns' },
  { id: 'detecting', label: 'Running detectors' },
]

const STAGE_MESSAGE: Record<string, string> = {
  queued: 'Analysis is queued.',
  validating: 'Validating the dataset.',
  parsing: 'Parsing the dataset.',
  profiling: 'Profiling columns.',
  detecting: 'Running detectors.',
}

export interface AnalysisStageProgressProps {
  /** A non-terminal `AnalysisState` value. Terminal states
   * (`completed`/`failed`/`cancelled`) are rendered by the caller, not
   * this component. */
  state: string
}

/** Domain component (`docs/ui-specification.md` §5). Wraps the named-
 * stage `Progress` primitive in a polite live region so stage changes
 * are announced to assistive technology (§4.3/§10). */
export function AnalysisStageProgress({ state }: AnalysisStageProgressProps) {
  const message = STAGE_MESSAGE[state] ?? 'Analysis is running.'

  return (
    <div role="status" aria-live="polite" className="flex flex-col gap-4">
      <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
        {message}
      </p>
      <Progress
        steps={STAGES}
        currentStepId={state}
        label="Analysis progress"
      />
    </div>
  )
}
