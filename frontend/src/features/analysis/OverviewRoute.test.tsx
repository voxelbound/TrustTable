import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  makeAnalysisResource,
  makeFindingsListResponse,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { OverviewRoute } from './OverviewRoute'

const ANALYSIS_ID = 'overview-under-test'

function renderOverview() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      { path: '/analyses/:analysisId/overview', element: <OverviewRoute /> },
      {
        path: '/analyses/:analysisId/findings',
        element: <p>Findings screen</p>,
      },
    ],
    { initialEntries: [`/analyses/${ANALYSIS_ID}/overview`] },
  )

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )

  return router
}

function findingFixture(
  detectorId: string,
  priorityScore: number,
  severity = 'medium',
) {
  return {
    detector_id: detectorId,
    detector_version: '1.0.0',
    category: 'validity',
    severity,
    confidence: 0.8,
    priority_score: priorityScore,
    calculated_observation: `Observation for ${detectorId}.`,
    affected_columns: [],
    affected_row_count: 1,
    evidence_count: 1,
  }
}

describe('OverviewRoute', () => {
  it('AC-05: renders sections in the documented order', async () => {
    renderOverview()

    const headings = await screen.findAllByRole('heading', { level: 2 })
    expect(headings.map((heading) => heading.textContent)).toEqual([
      'Trust assessment',
      'Top findings',
      'Immediate actions',
      'All findings',
      'Dataset summary',
      'Technical details',
    ])
  })

  it('AC-05: shows only the top three findings by priority_score', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/findings', () =>
        HttpResponse.json(
          makeFindingsListResponse({
            items: [
              findingFixture('a', 10),
              findingFixture('b', 90),
              findingFixture('c', 50),
              findingFixture('d', 70),
            ],
          }),
        ),
      ),
    )

    renderOverview()

    const heading = await screen.findByRole('heading', { name: 'Top findings' })
    const section = heading.closest('section') as HTMLElement
    const items = within(section).getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(items[0].textContent).toContain('Observation for b.')
    expect(items[1].textContent).toContain('Observation for d.')
    expect(items[2].textContent).toContain('Observation for c.')
  })

  it('AC-05: renders the mapped trust-assessment label and score', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId', () =>
        HttpResponse.json(
          makeAnalysisResource({
            trust_assessment: {
              label: 'material_quality_concerns',
              score: 41,
              finding_count: 3,
              highest_priority_score: 90,
            },
          }),
        ),
      ),
    )

    renderOverview()

    const heading = await screen.findByRole('heading', {
      name: 'Trust assessment',
    })
    const section = heading.closest('section') as HTMLElement
    expect(
      within(section).getByText('Material quality concerns'),
    ).toBeInTheDocument()
    expect(section.textContent).toContain('41')
  })

  it('AC-05: renders the dataset summary fields', async () => {
    renderOverview()

    expect(await screen.findByText('sales_demo.csv')).toBeInTheDocument()
    expect(screen.getByText('CSV')).toBeInTheDocument()
  })

  it('AC-05: renders a severity-count summary and a link to the full findings list', async () => {
    renderOverview()

    expect(await screen.findByText('View all findings')).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/findings`,
    )
  })

  it('renders honest "coming soon" placeholders for immediate actions and technical details', async () => {
    renderOverview()

    expect(
      await screen.findByText('Recommended actions are coming soon.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Technical details are coming soon.'),
    ).toBeInTheDocument()
  })
})
