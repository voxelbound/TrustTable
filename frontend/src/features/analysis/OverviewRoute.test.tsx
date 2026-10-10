import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  makeAnalysisResource,
  makeFindingsListResponse,
  makeSummaryResponse,
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
    finding_id: detectorId,
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
    review_state: 'unreviewed',
    note: null,
    dismissal_reason: null,
    reviewed_at: null,
  }
}

describe('OverviewRoute', () => {
  it('ING-03: names the analyzed worksheet for an Excel dataset', async () => {
    const base = makeAnalysisResource()
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId', () =>
        HttpResponse.json({
          ...base,
          dataset: {
            ...base.dataset,
            format: 'xlsx',
            original_filename: 'book.xlsx',
            selected_worksheet: 'Costs',
          },
        }),
      ),
    )
    renderOverview()

    const summary = (await screen.findByText('Dataset summary')).closest(
      'section',
    ) as HTMLElement
    expect(await within(summary).findByText('Worksheet analyzed')).toBeVisible()
    expect(within(summary).getByText('Costs')).toBeVisible()
    expect(within(summary).getByText('XLSX')).toBeVisible()
  })

  it('ING-03: shows no worksheet row for a CSV dataset', async () => {
    renderOverview()

    const summary = (await screen.findByText('Dataset summary')).closest(
      'section',
    ) as HTMLElement
    await within(summary).findByText('File name')
    expect(
      within(summary).queryByText('Worksheet analyzed'),
    ).not.toBeInTheDocument()
  })

  it('UX-04: renders the dashboard sections in order', async () => {
    renderOverview()

    await screen.findByText('Dataset summary')
    const headings = screen.getAllByRole('heading', { level: 2 })
    expect(headings.map((heading) => heading.textContent)).toEqual([
      'Trust assessment',
      'At a glance',
      'What was found',
      'Columns with the most findings',
      'Top findings',
      'Worth knowing',
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

  it('UX-04: no longer shows "coming soon" for capabilities that exist', async () => {
    renderOverview()

    await screen.findByText('Dataset summary')
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument()
    expect(screen.getByText('Open technical details')).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/technical`,
    )
  })

  it('UX-04: shows rows affected as distinct rows with the unlocated-findings caveat', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/summary', () =>
        HttpResponse.json(
          makeSummaryResponse({
            row_count: 300,
            rows_affected: 40,
            findings_without_row_detail: 2,
          }),
        ),
      ),
    )
    renderOverview()

    const glance = (await screen.findByText('At a glance')).closest(
      'section',
    ) as HTMLElement
    const rows = (await within(glance).findByText('Rows affected')).closest(
      'div',
    ) as HTMLElement
    expect(rows.textContent).toContain('40')
    expect(rows.textContent).toContain('of 300')
    expect(rows.textContent).toContain('each counted once')
    expect(rows.textContent).toContain(
      '2 findings concern a whole column or the whole file and name no row',
    )
    expect(rows.textContent).toContain('not necessarily clean')
  })

  it('UX-04: states a sampled completeness figure as a sample, not the whole file', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/summary', () =>
        HttpResponse.json(
          makeSummaryResponse({
            completeness: {
              scope: 'sampled',
              population_size: 1000000,
              sample_size: 50000,
              cells_total: 300000,
              cells_missing: 0,
              missing_share: 0,
            },
          }),
        ),
      ),
    )
    renderOverview()

    const figure = (await screen.findByText('Cells filled in')).closest(
      'div',
    ) as HTMLElement
    expect(figure.textContent).toContain(
      'Measured on a sample of 50,000 of 1,000,000 rows, not the whole file.',
    )
    expect(figure.textContent).not.toContain('Measured on all')
  })

  it('UX-04: rows affected also states the sample when the analysis is sampled', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/summary', () =>
        HttpResponse.json(
          makeSummaryResponse({
            row_count: 50000,
            rows_affected: 10,
            completeness: {
              scope: 'sampled',
              population_size: 1000000,
              sample_size: 50000,
              cells_total: 300000,
              cells_missing: 5,
              missing_share: 5 / 300000,
            },
          }),
        ),
      ),
    )
    renderOverview()

    const rows = (await screen.findByText('Rows affected')).closest(
      'div',
    ) as HTMLElement
    expect(rows.textContent).toContain(
      'a count within a sample of 50,000 of 1,000,000 rows, not the whole file',
    )
  })

  it('UX-04: rows affected makes no sample claim when the scope is full', async () => {
    renderOverview()

    const rows = (await screen.findByText('Rows affected')).closest(
      'div',
    ) as HTMLElement
    expect(rows.textContent).not.toContain('within a sample')
  })

  it('UX-04: a full-scope completeness figure says it covers every row', async () => {
    renderOverview()

    const figure = (await screen.findByText('Cells filled in')).closest(
      'div',
    ) as HTMLElement
    expect(figure.textContent).toContain('99%')
    expect(figure.textContent).toContain('18 of 1,800 cells are empty')
    expect(figure.textContent).toContain('Measured on all 300 rows.')
  })

  it('UX-04: shows severity and category distributions in business wording', async () => {
    renderOverview()

    const section = (await screen.findByText('What was found')).closest(
      'section',
    ) as HTMLElement
    const severity = within(section).getByRole('list', { name: 'By severity' })
    expect(within(severity).getByText('High')).toBeVisible()
    expect(within(severity).getByText('Low')).toBeVisible()
    const kind = within(section).getByRole('list', {
      name: 'By kind of problem',
    })
    expect(within(kind).getByText('Valid values')).toBeVisible()
    expect(within(kind).getByText('Consistency')).toBeVisible()
    // Raw internal category values never appear.
    expect(section.textContent).not.toContain('cross_field')
    expect(section.textContent).not.toContain('validity')
  })

  it('UX-04: lists the columns with the most findings', async () => {
    renderOverview()

    const section = (
      await screen.findByText('Columns with the most findings')
    ).closest('section') as HTMLElement
    expect(within(section).getByText('order_date')).toBeVisible()
    expect(within(section).getByText('category')).toBeVisible()
  })

  it('UX-04: shows review progress from the findings', async () => {
    const reviewed = {
      ...findingFixture('a', 10),
      review_state: 'confirmed',
    }
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/findings', () =>
        HttpResponse.json(
          makeFindingsListResponse({
            items: [reviewed, findingFixture('b', 20), findingFixture('c', 30)],
          }),
        ),
      ),
    )
    renderOverview()

    const figure = (await screen.findByText('Review progress')).closest(
      'div',
    ) as HTMLElement
    expect(figure.textContent).toContain('1')
    expect(figure.textContent).toContain('of 3 findings reviewed')
    expect(figure.textContent).toContain('Unreviewed: 2')
    expect(figure.textContent).toContain('Confirmed: 1')
  })

  it('UX-04: shows the empty states when nothing was found', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/findings', () =>
        HttpResponse.json(makeFindingsListResponse({ items: [] })),
      ),
    )
    renderOverview()

    expect(
      await screen.findByText('No finding points at a specific column.'),
    ).toBeVisible()
    expect(screen.getAllByText('No findings were identified.')).toHaveLength(2)
    expect(screen.getByText('There is nothing to review.')).toBeVisible()
  })

  it('UX-04: a failed summary request does not block the rest of the page', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/summary', () =>
        HttpResponse.json(
          { error: { code: 'X', message: 'x' } },
          { status: 500 },
        ),
      ),
    )
    renderOverview()

    expect(
      await screen.findByText(
        'Row and completeness figures could not be loaded.',
      ),
    ).toBeVisible()
    expect(screen.getByText('Top findings')).toBeVisible()
    expect(screen.getByText('Review progress')).toBeVisible()
  })

  it('UX-04: a failed findings request is shown as unknown, never as a clean file', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/findings', () =>
        HttpResponse.json(
          { error: { code: 'X', message: 'x' } },
          { status: 500 },
        ),
      ),
    )
    renderOverview()

    await screen.findByText('Dataset summary')
    expect(
      screen.getAllByText('The findings could not be loaded.'),
    ).toHaveLength(3)
    expect(screen.getByText('Not available')).toBeVisible()
    expect(screen.queryByText('No findings were identified.')).toBeNull()
    expect(
      screen.queryByText('No finding points at a specific column.'),
    ).toBeNull()
    expect(screen.queryByText('There is nothing to review.')).toBeNull()
  })

  it('UX-04: says AI explanations are separate and optional, and never claims AI ran', async () => {
    renderOverview()

    const glance = (await screen.findByText('At a glance')).closest(
      'section',
    ) as HTMLElement
    expect(glance.textContent).toContain('AI explanations are optional')
    expect(glance.textContent).toContain('built-in checks')
  })

  it('UI-02 slice 2 (WP-064): renders a link to the Context screen', async () => {
    renderOverview()

    expect(await screen.findByText('Review dataset context')).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/context`,
    )
  })
})
