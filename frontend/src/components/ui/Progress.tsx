export interface ProgressStep {
  id: string
  label: string
}

export interface ProgressProps {
  steps: ProgressStep[]
  currentStepId: string
  label: string
}

/** Shared named-stage progress primitive (`docs/ui-specification.md`
 * §4.3: "Show named stages, not only a spinner"; §5). Purely visual
 * step state — callers own the surrounding live-region announcement
 * (see `components/provenance/AnalysisStageProgress.tsx`). */
export function Progress({ steps, currentStepId, label }: ProgressProps) {
  const currentIndex = steps.findIndex((step) => step.id === currentStepId)

  return (
    <ol aria-label={label} className="flex flex-col gap-2">
      {steps.map((step, index) => {
        const isCurrent = step.id === currentStepId
        const isComplete = currentIndex >= 0 && index < currentIndex
        const textClass = isCurrent
          ? 'font-semibold text-slate-900 dark:text-slate-100'
          : isComplete
            ? 'text-slate-500 dark:text-slate-400 line-through'
            : 'text-slate-400 dark:text-slate-500'

        return (
          <li
            key={step.id}
            aria-current={isCurrent ? 'step' : undefined}
            className={`flex items-center gap-2 text-sm ${textClass}`}
          >
            <span aria-hidden="true">
              {isComplete ? '✓' : isCurrent ? '→' : '○'}
            </span>
            <span>{step.label}</span>
          </li>
        )
      })}
    </ol>
  )
}
