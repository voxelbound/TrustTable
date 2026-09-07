import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PromptInjectionWarning } from './PromptInjectionWarning'

describe('PromptInjectionWarning', () => {
  it('AC-05: renders title, category, affected field, and the safe description', () => {
    render(
      <PromptInjectionWarning
        affectedColumns={[{ original_name: 'notes' }]}
        evidenceSummaries={[
          "Column 'notes' has 1 value(s) with possible instruction-like content.",
        ]}
        securityExposure={{
          model_provider_enabled: false,
          sample_transmission_enabled: false,
        }}
      />,
    )

    expect(
      screen.getByText('Potential prompt-injection content detected'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Category: AI processing security'),
    ).toBeInTheDocument()
    expect(screen.getByText('notes')).toBeInTheDocument()
    expect(
      screen.getByText(
        "Column 'notes' has 1 value(s) with possible instruction-like content.",
      ),
    ).toBeInTheDocument()
  })

  it('AC-05: reports sent-to-model status and model location from security_exposure', () => {
    render(
      <PromptInjectionWarning
        affectedColumns={[{ original_name: 'notes' }]}
        evidenceSummaries={[]}
        securityExposure={{
          model_provider_enabled: false,
          sample_transmission_enabled: false,
        }}
      />,
    )

    expect(screen.getByText('No')).toBeInTheDocument()
    expect(screen.getByText('No AI model is configured')).toBeInTheDocument()
  })

  it('AC-05: never asserts malicious intent as fact', () => {
    render(
      <PromptInjectionWarning
        affectedColumns={[{ original_name: 'notes' }]}
        evidenceSummaries={[]}
        securityExposure={{
          model_provider_enabled: false,
          sample_transmission_enabled: false,
        }}
      />,
    )

    expect(
      screen.getByText(/This does not confirm malicious intent\./),
    ).toBeInTheDocument()
  })

  it('AC-05: lists real, static SEC-02 protections rather than fabricated per-finding content', () => {
    render(
      <PromptInjectionWarning
        affectedColumns={[{ original_name: 'notes' }]}
        evidenceSummaries={[]}
        securityExposure={{
          model_provider_enabled: false,
          sample_transmission_enabled: false,
        }}
      />,
    )

    expect(
      screen.getByText('Sample sending to a model is disabled by default.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Deterministic findings and the risk score cannot be removed or altered by AI interpretation.',
      ),
    ).toBeInTheDocument()
  })

  it('renders a fallback when no affected column or evidence summary is available', () => {
    render(
      <PromptInjectionWarning
        affectedColumns={[]}
        evidenceSummaries={[]}
        securityExposure={{
          model_provider_enabled: false,
          sample_transmission_enabled: false,
        }}
      />,
    )

    expect(
      screen.getByText('No affected column was reported.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('No further description is available for this finding.'),
    ).toBeInTheDocument()
  })
})
