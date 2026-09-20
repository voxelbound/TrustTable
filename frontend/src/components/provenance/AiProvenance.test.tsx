import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AiProvenanceResponse } from '../../api'
import { AiProvenance } from './AiProvenance'
import {
  explanationCallStatusLabel,
  formatAiIdentity,
} from './aiProvenanceLabels'

const BASELINE: AiProvenanceResponse = {
  deployment_label: 'Local AI',
  runtime_label: 'llama.cpp',
  model_label: 'Qwen3.5 4B',
  quantization: 'Q4_K_M',
  model_identifier: 'Qwen3.5-4B-Q4_K_M.gguf',
}

describe('formatAiIdentity', () => {
  it('composes deployment, runtime and model with the quantization', () => {
    expect(formatAiIdentity(BASELINE)).toBe(
      'Local AI · llama.cpp · Qwen3.5 4B (Q4_K_M)',
    )
  })

  it('omits the quantization when none was derived', () => {
    expect(formatAiIdentity({ ...BASELINE, quantization: null })).toBe(
      'Local AI · llama.cpp · Qwen3.5 4B',
    )
  })

  it('omits the model when no label could be derived, never falling back to the identifier', () => {
    const text = formatAiIdentity({
      ...BASELINE,
      model_label: null,
      quantization: null,
    })
    expect(text).toBe('Local AI · llama.cpp')
    expect(text).not.toContain('gguf')
  })

  it('never renders the sanitized diagnostic identifier', () => {
    expect(formatAiIdentity(BASELINE)).not.toContain('.gguf')
  })
})

describe('explanationCallStatusLabel', () => {
  it('describes each status without ever claiming AI is disabled', () => {
    expect(explanationCallStatusLabel('attempted_accepted')).toBe('')
    expect(explanationCallStatusLabel('not_configured')).toBe(
      'no AI provider is configured',
    )
    expect(explanationCallStatusLabel('attempted_rejected')).toMatch(
      /did not produce a usable result/,
    )
    expect(explanationCallStatusLabel('attempted_provider_error')).toMatch(
      /could not complete/,
    )
    for (const status of [
      'not_configured',
      'attempted_accepted',
      'attempted_rejected',
      'attempted_provider_error',
    ] as const) {
      expect(explanationCallStatusLabel(status)).not.toMatch(/disabled/i)
    }
  })
})

describe('AiProvenance', () => {
  it('shows the human-readable identity for an accepted AI interpretation', () => {
    render(
      <AiProvenance
        provenance="ai_interpretation"
        aiProvenance={BASELINE}
        aiCallStatus="attempted_accepted"
      />,
    )
    expect(
      screen.getByText(
        'AI interpretation — Local AI · llama.cpp · Qwen3.5 4B (Q4_K_M)',
      ),
    ).toBeInTheDocument()
  })

  it('shows built-in guidance and the reason when no AI result is shown', () => {
    render(
      <AiProvenance
        provenance="deterministic_fallback"
        aiProvenance={null}
        aiCallStatus="attempted_provider_error"
      />,
    )
    expect(
      screen.getByText(
        'Built-in TrustTable guidance (no AI) — an AI attempt for this analysis could not complete',
      ),
    ).toBeInTheDocument()
  })

  it('says built-in guidance with no AI configured', () => {
    render(
      <AiProvenance
        provenance="deterministic_fallback"
        aiProvenance={null}
        aiCallStatus="not_configured"
      />,
    )
    expect(
      screen.getByText(
        'Built-in TrustTable guidance (no AI) — no AI provider is configured',
      ),
    ).toBeInTheDocument()
  })

  it('shows no identity for an accepted interpretation that carries no provenance', () => {
    render(
      <AiProvenance
        provenance="ai_interpretation"
        aiProvenance={null}
        aiCallStatus="attempted_accepted"
      />,
    )
    expect(screen.getByText('AI interpretation')).toBeInTheDocument()
  })
})
