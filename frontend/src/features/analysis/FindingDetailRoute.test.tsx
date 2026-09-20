import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  apiErrorBody,
  makeFindingDetailResponse,
  makeFindingEvidenceListResponse,
  makeFindingExplanationResponse,
  makeRowContextResponse,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { FindingDetailRoute } from './FindingDetailRoute'

const ANALYSIS_ID = 'finding-detail-under-test'
const FINDING_ID = '0'

function renderDetail(findingId = FINDING_ID) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      {
        path: '/analyses/:analysisId/findings/:findingId',
        element: <FindingDetailRoute />,
      },
      {
        path: '/analyses/:analysisId/findings',
        element: <p>Findings screen</p>,
      },
    ],
    {
      initialEntries: [`/analyses/${ANALYSIS_ID}/findings/${findingId}`],
    },
  )

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )

  return router
}

describe('FindingDetailRoute', () => {
  it('AC-02: renders the observation and technical metadata from GET .../findings/{finding_id}', async () => {
    renderDetail()

    expect(
      await screen.findByText('order_date has 2 future dates.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('validity.future_dates (v1.0.0)'),
    ).toBeInTheDocument()
    expect(screen.getByText('90%')).toBeInTheDocument()
    expect(screen.getByText('80')).toBeInTheDocument()
  })

  it('AC-03: renders evidence items under "Evidence"', async () => {
    renderDetail()

    const heading = await screen.findByRole('heading', { name: 'Evidence' })
    expect(heading).toBeInTheDocument()
    expect(
      screen.getByText("Column 'order_date' has 2 future date value(s)."),
    ).toBeInTheDocument()
  })

  it('AC-03: renders representative_sample evidence under "Representative examples" instead of "Evidence"', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/evidence',
        () =>
          HttpResponse.json(
            makeFindingEvidenceListResponse({
              items: [
                {
                  evidence_id: 'x.evidence.representative',
                  evidence_type: 'representative_sample',
                  display_safe_summary: 'A representative example summary.',
                  affected_columns: [],
                  affected_row_count: 1,
                  scope: 'full',
                },
              ],
            }),
          ),
      ),
    )

    renderDetail()

    expect(
      await screen.findByRole('heading', { name: 'Representative examples' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('A representative example summary.'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('No evidence items were recorded for this finding.'),
    ).toBeInTheDocument()
  })

  it('AI-08: the business impact, remediation and validation rule placeholders are gone; only review controls remains not yet available', async () => {
    renderDetail()

    await screen.findByRole('heading', { name: 'Observation' })
    expect(await screen.findByText(/Not yet available/)).toBeInTheDocument()
    // Exactly one "Not yet available" remains: persistent finding review.
    expect(screen.getAllByText(/Not yet available/)).toHaveLength(1)
    expect(
      screen.getByText(
        'Not yet available — persistent finding review is a later backlog item.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/business-impact analysis is a later/)).toBeNull()
    expect(
      screen.queryByText(/remediation recommendations are a later/),
    ).toBeNull()
    expect(
      screen.queryByText(/proposed validation rules are a later/),
    ).toBeNull()
  })

  it('AI-08: renders all four analysis sections from one response, with built-in guidance when no AI is configured', async () => {
    renderDetail()

    expect(
      await screen.findByRole('heading', { name: 'Explanation' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Possible business impact' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Remediation' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Validation rule' }),
    ).toBeInTheDocument()
    // Built-in guidance content, not placeholders.
    expect(
      screen.getByText(
        /Dates later than the analysis date may be typing errors/,
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Conditional')).toBeInTheDocument()
    expect(
      screen.getByText(
        /Assumes: the column is meant to record events that have already happened/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Check the flagged rows and correct any mistyped dates/),
    ).toBeInTheDocument()
    expect(screen.getByText('Proposed — not active')).toBeInTheDocument()
    expect(screen.getByText('Date range')).toBeInTheDocument()
    expect(screen.getByText(/Applies to: order_date/)).toBeInTheDocument()
    expect(
      screen.getByText(/TrustTable never changes your uploaded data/),
    ).toBeInTheDocument()
    expect(screen.getByText(/does not run or enforce it/)).toBeInTheDocument()
  })

  it('AI-08: an accepted AI analysis presents impact as conditional or context-informed, never evidence-backed, and labels the provenance without any filesystem path', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/explanation',
        () =>
          HttpResponse.json(
            makeFindingExplanationResponse({
              narrative: 'The evidence records 2 affected row(s).',
              provenance: 'ai_interpretation',
              provider_name: 'llama_cpp',
              // A leaky backend must still never reach the screen: the UI
              // renders only `ai_provenance`'s labels.
              model_identifier: String.raw`C:\LocalAI\TrustTable\models\Qwen3.5-9B-Q4_K_M.gguf`,
              ai_provenance: {
                deployment_label: 'Local AI',
                runtime_label: 'llama.cpp',
                model_label: 'Qwen3.5 9B',
                quantization: 'Q4_K_M',
                model_identifier: 'Qwen3.5-9B-Q4_K_M.gguf',
              },
              ai_call_status: 'attempted_accepted',
              evidence_sent_to_model: true,
              confirmed_context_sent_to_model: true,
              business_impact: [
                {
                  statement:
                    'This will cause the company to lose money and damage its reputation.',
                  basis: 'assumption',
                  evidence_ids: ['validity.future_dates.evidence.order_date'],
                  context_fields: [],
                  assumption: 'the flagged rows are used in reports',
                },
                {
                  statement:
                    'This matters given the confirmed dataset context.',
                  basis: 'confirmed_context',
                  evidence_ids: [],
                  context_fields: ['row_grain'],
                  assumption: 'orders are counted per row',
                },
                {
                  statement: 'Reports built on this data may be affected.',
                  basis: 'assumption',
                  evidence_ids: [],
                  context_fields: [],
                  assumption: 'the affected values feed reports',
                },
              ],
              remediation: ['Fix the flagged dates at the source.'],
              validation_rule: {
                rule_type: 'not_null',
                columns: [],
                description: 'Proposed: values should be filled in.',
                status: 'proposed',
              },
            }),
          ),
      ),
    )

    renderDetail()

    expect(
      await screen.findByText(
        'AI interpretation — Local AI · llama.cpp · Qwen3.5 9B (Q4_K_M)',
      ),
    ).toBeInTheDocument()
    // Impact statements are potential impacts: conditional, or informed by
    // confirmed context — and never "Evidence-backed", whatever the model
    // wrote (here: an invented loss and reputation harm).
    expect(screen.getAllByText('Conditional')).toHaveLength(2)
    expect(
      screen.getByText('Informed by your confirmed context'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Evidence-backed/i)).toBeNull()
    expect(
      screen.getByText(/lose money and damage its reputation/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Assumes: the flagged rows are used in reports/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Draws on your confirmed row grain/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Assumes: the affected values feed reports/),
    ).toBeInTheDocument()
    expect(screen.getByText('Proposed — not active')).toBeInTheDocument()
    expect(
      screen.getByText(/along with your confirmed dataset context/),
    ).toBeInTheDocument()
    // No absolute host path anywhere on the page.
    const page = document.body.textContent ?? ''
    for (const fragment of ['C:\\', 'LocalAI', 'TrustTable\\models', '.gguf']) {
      expect(page).not.toContain(fragment)
    }
  })

  it('AI-08: a rejected AI attempt keeps all four sections (built-in guidance) and discloses the rejection', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/explanation',
        () =>
          HttpResponse.json(
            makeFindingExplanationResponse({
              ai_call_status: 'attempted_rejected',
              evidence_sent_to_model: true,
            }),
          ),
      ),
    )

    renderDetail()

    expect(
      await screen.findByText(
        /Built-in TrustTable guidance \(no AI\) — an AI attempt for this analysis did not produce a usable result/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Possible business impact' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Remediation' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Proposed — not active')).toBeInTheDocument()
  })

  it('AI-08: a finding with no impact, steps or rule still renders honest empty states, not placeholders', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/explanation',
        () =>
          HttpResponse.json(
            makeFindingExplanationResponse({
              business_impact: [],
              remediation: [],
              validation_rule: null,
            }),
          ),
      ),
    )

    renderDetail()

    expect(
      await screen.findByText(
        'No business-impact statements were produced for this finding.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText('No remediation steps were produced for this finding.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('No validation rule was proposed for this finding.'),
    ).toBeInTheDocument()
  })

  it('AC-05: renders the dedicated prompt-injection warning for ai_processing_security findings, not the generic evidence list', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId',
        () =>
          HttpResponse.json(
            makeFindingDetailResponse({
              category: 'ai_processing_security',
              detector_id: 'security.possible_llm_prompt_injection',
              calculated_observation:
                "Column 'notes' has 1 value(s) with possible instruction-like content.",
            }),
          ),
      ),
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/evidence',
        () =>
          HttpResponse.json(
            makeFindingEvidenceListResponse({
              items: [
                {
                  evidence_id:
                    'security.possible_llm_prompt_injection.evidence.notes',
                  evidence_type: 'security_pattern',
                  display_safe_summary:
                    "Column 'notes' has 1 value(s) with possible instruction-like content matching 2 pattern categories.",
                  affected_columns: [
                    {
                      original_name: 'notes',
                      internal_key: 'notes',
                      ordinal: 9,
                    },
                  ],
                  affected_row_count: 1,
                  scope: 'full',
                },
              ],
            }),
          ),
      ),
    )

    renderDetail()

    expect(
      await screen.findByText('Potential prompt-injection content detected'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Category: AI processing security'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        "Column 'notes' has 1 value(s) with possible instruction-like content matching 2 pattern categories.",
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/This does not confirm malicious intent\./),
    ).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Evidence' })).toBeNull()
  })

  it('AC-06: renders a structured 404 as an inline alert with a link back to findings, not a stack trace', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId',
        () =>
          HttpResponse.json(
            apiErrorBody('FINDING_NOT_FOUND', 'Finding not found.'),
            { status: 404 },
          ),
      ),
    )

    renderDetail('999')

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Finding not found.')
    expect(alert.textContent).not.toContain('at ')
    expect(
      screen.getByRole('link', { name: 'Back to findings' }),
    ).toHaveAttribute('href', `/analyses/${ANALYSIS_ID}/findings`)
  })

  it('UI-02 slice 1 (WP-063): renders the deterministic Explanation section with no model-location text', async () => {
    renderDetail()

    expect(
      await screen.findByRole('heading', { name: 'Explanation' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('This is a medium-severity finding worth reviewing.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Built-in TrustTable guidance \(no AI\)/),
    ).toBeInTheDocument()
    expect(screen.getByText(/no AI provider is configured/)).toBeInTheDocument()
    // D-038 axis 5: nothing was sent to a model, since no attempt was made.
    expect(
      screen.queryByText(/evidence was sent to the model/),
    ).not.toBeInTheDocument()
  })

  it('WP-065: distinguishes an attempted-and-rejected AI explanation from never-attempted, without claiming AI is disabled', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/explanation',
        () =>
          HttpResponse.json(
            makeFindingExplanationResponse({
              ai_call_status: 'attempted_rejected',
              evidence_sent_to_model: true,
            }),
          ),
      ),
    )

    renderDetail()

    expect(
      await screen.findByRole('heading', { name: 'Explanation' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Built-in TrustTable guidance \(no AI\)/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /an AI attempt for this analysis did not produce a usable result/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /This finding's evidence was sent to the model for this request/,
      ),
    ).toBeInTheDocument()
  })

  it('WP-065: distinguishes an attempted-and-errored AI explanation with its own status text', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/explanation',
        () =>
          HttpResponse.json(
            makeFindingExplanationResponse({
              ai_call_status: 'attempted_provider_error',
            }),
          ),
      ),
    )

    renderDetail()

    expect(
      await screen.findByRole('heading', { name: 'Explanation' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/an AI attempt for this analysis could not complete/),
    ).toBeInTheDocument()
  })

  it('WP-065 r4: no rendered string claims no AI call was made or no AI model is configured while an accepted AI explanation is shown for an ai_processing_security finding, the removed generic "AI model enabled" row is gone, and evidence-sent-to-model (D-038 axis 5) is disclosed', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId',
        () =>
          HttpResponse.json(
            makeFindingDetailResponse({
              category: 'ai_processing_security',
              detector_id: 'security.possible_llm_prompt_injection',
              calculated_observation:
                "Column 'notes' has 1 value(s) with possible instruction-like content.",
            }),
          ),
      ),
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/evidence',
        () =>
          HttpResponse.json(
            makeFindingEvidenceListResponse({
              items: [
                {
                  evidence_id:
                    'security.possible_llm_prompt_injection.evidence.notes',
                  evidence_type: 'security_pattern',
                  display_safe_summary:
                    "Column 'notes' has 1 value(s) with possible instruction-like content.",
                  affected_columns: [
                    {
                      original_name: 'notes',
                      internal_key: 'notes',
                      ordinal: 9,
                    },
                  ],
                  affected_row_count: 1,
                  scope: 'full',
                },
              ],
            }),
          ),
      ),
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/explanation',
        () =>
          HttpResponse.json(
            makeFindingExplanationResponse({
              narrative: 'An AI-grounded narrative.',
              provenance: 'ai_interpretation',
              provider_name: 'llama_cpp',
              model_identifier: 'Qwen3.5-4B-Q4_K_M',
              ai_provenance: {
                deployment_label: 'Local AI',
                runtime_label: 'llama.cpp',
                model_label: 'Qwen3.5 4B',
                quantization: 'Q4_K_M',
                model_identifier: 'Qwen3.5-4B-Q4_K_M',
              },
              ai_call_status: 'attempted_accepted',
              evidence_sent_to_model: true,
              confirmed_context_sent_to_model: false,
            }),
          ),
      ),
    )

    renderDetail()

    expect(
      await screen.findByText(
        'AI interpretation — Local AI · llama.cpp · Qwen3.5 4B (Q4_K_M)',
      ),
    ).toBeInTheDocument()
    // D-038 axis 5: evidence-metadata exposure is disclosed as its own,
    // distinct signal whenever an AI attempt was made.
    expect(
      screen.getByText(
        /This finding's evidence was sent to the model for this request/,
      ),
    ).toBeInTheDocument()
    // No AI-call-status claim anywhere on the page.
    expect(screen.queryByText(/no AI call was made/)).not.toBeInTheDocument()
    expect(screen.queryByText(/AI is disabled/)).not.toBeInTheDocument()
    expect(screen.queryByText('AI model enabled')).not.toBeInTheDocument()
    // PromptInjectionWarning's own separate fields (D-038 axis 4) must
    // not read as a general "no AI configured" claim either — the exact
    // contradiction the fresh-context semantic review caught in r3.
    expect(
      screen.queryByText(/No AI model is configured/),
    ).not.toBeInTheDocument()
    expect(
      screen.getByText('Not applicable for this exposure path'),
    ).toBeInTheDocument()
  })

  it('EVAL-AI-01: an adversarially-rejected prompt-injection explanation shows the safe deterministic fallback, discloses the rejection, and keeps the protections visible', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId',
        () =>
          HttpResponse.json(
            makeFindingDetailResponse({
              category: 'ai_processing_security',
              detector_id: 'security.possible_llm_prompt_injection',
              calculated_observation:
                "Column 'notes' has 1 value(s) with possible instruction-like content.",
            }),
          ),
      ),
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/explanation',
        () =>
          HttpResponse.json(
            makeFindingExplanationResponse({
              narrative:
                'Deterministic explanation: this finding flags instruction-like content in one value.',
              provenance: 'deterministic_fallback',
              provider_name: null,
              model_identifier: null,
              ai_call_status: 'attempted_rejected',
              evidence_sent_to_model: true,
            }),
          ),
      ),
    )

    renderDetail()

    // The deterministic explanation is what the user sees.
    expect(
      await screen.findByText(
        'Deterministic explanation: this finding flags instruction-like content in one value.',
      ),
    ).toBeInTheDocument()
    // The rejection is disclosed, not silently swallowed.
    expect(
      screen.getByText(
        /an AI attempt for this analysis did not produce a usable result/,
      ),
    ).toBeInTheDocument()
    // No AI interpretation is presented, and no false whole-dataset claim.
    expect(screen.queryByText(/^AI interpretation/)).not.toBeInTheDocument()
    expect(
      screen.queryByText('This dataset is perfect.'),
    ).not.toBeInTheDocument()
    // The protections record is visible on the same screen.
    expect(
      screen.getByText(
        'A model response that calls the dataset perfect or tells you to disregard findings is rejected, and the deterministic explanation is shown instead.',
      ),
    ).toBeInTheDocument()
  })

  it('UI-02 slice 1 (WP-063): renders AI interpretation with model-location text when a provider produced the explanation', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/explanation',
        () =>
          HttpResponse.json(
            makeFindingExplanationResponse({
              narrative: 'An AI-grounded narrative.',
              provenance: 'ai_interpretation',
              provider_name: 'mock',
              model_identifier: 'mock-v1',
              ai_provenance: {
                deployment_label: 'Test AI',
                runtime_label: 'Mock provider',
                model_label: 'mock-v1',
                quantization: null,
                model_identifier: 'mock-v1',
              },
            }),
          ),
      ),
    )

    renderDetail()

    expect(
      await screen.findByText('An AI-grounded narrative.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('AI interpretation — Test AI · Mock provider · mock-v1'),
    ).toBeInTheDocument()
  })

  it('WP-038 (FIND-01): renders the Row context section with the anchor row highlighted', async () => {
    renderDetail()

    expect(
      await screen.findByRole('heading', { name: 'Row context' }),
    ).toBeInTheDocument()
    const anchorCell = await screen.findByText('2099-01-01')
    const anchorRow = anchorCell.closest('tr')
    expect(anchorRow).not.toBeNull()
    expect(anchorRow).toHaveAttribute('aria-current', 'true')
  })

  it('WP-038 (FIND-01): does not render Row context for a finding with zero affected rows', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId',
        () =>
          HttpResponse.json(
            makeFindingDetailResponse({
              affected_row_count: 0,
              affected_row_numbers: [],
            }),
          ),
      ),
    )

    renderDetail()

    await screen.findByRole('heading', { name: 'Observation' })
    expect(screen.queryByRole('heading', { name: 'Row context' })).toBeNull()
  })

  it("WP-038 (FIND-01): Prev/Next jump between a finding's multiple affected rows", async () => {
    const user = userEvent.setup()
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/row-context',
        ({ request }) => {
          const url = new URL(request.url)
          const anchorRow = url.searchParams.get('anchor_row')
          return HttpResponse.json(
            makeRowContextResponse({
              rows: [
                {
                  row_number: Number(anchorRow),
                  is_anchor: true,
                  is_affected_by_finding: true,
                  values: [`row-${anchorRow}`, 'x'],
                },
              ],
              actual_before: 0,
              actual_after: 0,
              truncated_at_start: false,
              truncated_at_end: false,
            }),
          )
        },
      ),
    )

    renderDetail()

    expect(await screen.findByText('Affected row 1 of 2')).toBeInTheDocument()
    expect(await screen.findByText('row-4')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Next' }))

    expect(await screen.findByText('Affected row 2 of 2')).toBeInTheDocument()
    expect(await screen.findByText('row-17')).toBeInTheDocument()
  })

  it('WP-038 (FIND-01): Show more rows expands the requested window', async () => {
    const user = userEvent.setup()
    let lastBefore: string | null = null
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/row-context',
        ({ request }) => {
          const url = new URL(request.url)
          lastBefore = url.searchParams.get('before')
          return HttpResponse.json(makeRowContextResponse())
        },
      ),
    )

    renderDetail()

    const expandButton = await screen.findByRole('button', {
      name: 'Show more rows',
    })
    await user.click(expandButton)

    expect(lastBefore).toBe('8')
  })
})
