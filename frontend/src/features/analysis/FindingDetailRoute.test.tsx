import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  apiErrorBody,
  makeFindingDetailResponse,
  makeFindingEvidenceListResponse,
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

  it('AC-04: renders honest not-yet-available placeholders for unbuilt §4.7 sections', async () => {
    renderDetail()

    await screen.findByRole('heading', { name: 'Observation' })
    expect(
      screen.getByText(
        'Not yet available — business-impact analysis is a later backlog item.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Not yet available — remediation recommendations are a later backlog item.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Not yet available — proposed validation rules are a later backlog item.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Not yet available — persistent finding review is a later backlog item.',
      ),
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
})
