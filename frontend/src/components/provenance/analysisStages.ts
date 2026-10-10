import type { ProgressStep } from '../ui/Progress'

/** The five non-terminal `AnalysisState` values, in pipeline order
 * (`analysis/service.py`), in business wording (`UX-04`, D-070). The
 * wording describes what is being done to the person's file, never a
 * detector or pipeline name. */
export const ANALYSIS_STAGES: ProgressStep[] = [
  { id: 'queued', label: 'Waiting to start' },
  { id: 'validating', label: 'Checking the file' },
  { id: 'parsing', label: 'Reading the rows' },
  { id: 'profiling', label: 'Measuring each column' },
  { id: 'detecting', label: 'Looking for data-quality problems' },
]

export const ANALYSIS_STAGE_MESSAGE: Record<string, string> = {
  queued: 'Your analysis is waiting to start.',
  validating: 'Checking that the file can be read.',
  parsing: 'Reading the rows of your file.',
  profiling: 'Measuring each column.',
  detecting: 'Looking for data-quality problems.',
}
