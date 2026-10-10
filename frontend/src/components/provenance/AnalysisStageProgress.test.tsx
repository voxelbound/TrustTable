import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AnalysisStageProgress } from './AnalysisStageProgress'
import { ANALYSIS_STAGE_MESSAGE, ANALYSIS_STAGES } from './analysisStages'

describe('AnalysisStageProgress (UX-04)', () => {
  it('uses business wording with no detector or pipeline internals', () => {
    const text = [
      ...ANALYSIS_STAGES.map((stage) => stage.label),
      ...Object.values(ANALYSIS_STAGE_MESSAGE),
    ].join(' | ')
    expect(text).not.toMatch(
      /detector|pipeline|profil(e|ing) columns|parsing|dataset/i,
    )
  })

  it('names a message for every non-terminal stage', () => {
    for (const stage of ANALYSIS_STAGES) {
      expect(ANALYSIS_STAGE_MESSAGE[stage.id]).toBeTruthy()
    }
  })

  it('says results are ready when the steps finish and that AI work is separate and optional', () => {
    render(<AnalysisStageProgress state="profiling" />)

    expect(screen.getByText('Measuring each column.')).toBeVisible()
    const note = screen.getByText(
      /Your results are ready when these steps finish/,
    )
    expect(note.textContent).toContain('AI explanations are optional')
    expect(note.textContent).toContain('never delay your results')
  })

  it('shows no time estimate or percentage', () => {
    const { container } = render(<AnalysisStageProgress state="detecting" />)

    expect(container.textContent).not.toMatch(
      /\d+\s*%|minutes?|seconds?|remaining|\bETA\b/i,
    )
  })

  it('does not imply AI has run or finished', () => {
    const { container } = render(<AnalysisStageProgress state="detecting" />)

    expect(container.textContent).not.toMatch(
      /AI (analysis|is|has|finished|complete)|analysed by AI/i,
    )
  })
})
