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
