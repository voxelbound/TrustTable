import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import { makeFindingsListResponse } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { FindingsRoute } from './FindingsRoute'

const ANALYSIS_ID = 'findings-under-test'

const FIXTURE_ITEMS = [
  {
    finding_id: '0',
    detector_id: 'validity.future_dates',
    detector_version: '1.0.0',
    category: 'validity',
    severity: 'critical',
    confidence: 0.9,
    priority_score: 90,
    calculated_observation: 'order_date has future dates.',
    affected_columns: [
      { original_name: 'order_date', internal_key: 'order_date', ordinal: 0 },
    ],
    affected_row_count: 2,
    evidence_count: 2,
    review_state: 'unreviewed',
    note: null,
    dismissal_reason: null,
    reviewed_at: null,
  },
  {
    finding_id: '1',
    detector_id: 'consistency.inconsistent_capitalization',
    detector_version: '1.0.0',
    category: 'consistency',
    severity: 'low',
    confidence: 0.6,
    priority_score: 20,
    calculated_observation: 'category has inconsistent capitalization.',
    affected_columns: [
      { original_name: 'category', internal_key: 'category', ordinal: 1 },
    ],
    affected_row_count: 83,
    evidence_count: 2,
    review_state: 'unreviewed',
    note: null,
    dismissal_reason: null,
    reviewed_at: null,
  },
]

function renderFindings(searchSuffix = '') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [{ path: '/analyses/:analysisId/findings', element: <FindingsRoute /> }],
    {
      initialEntries: [`/analyses/${ANALYSIS_ID}/findings${searchSuffix}`],
    },
  )

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )

  return router
}

function useFixtureFindings() {
  server.use(
    http.get('http://localhost/api/v1/analyses/:analysisId/findings', () =>
      HttpResponse.json(makeFindingsListResponse({ items: FIXTURE_ITEMS })),
    ),
  )
}

describe('FindingsRoute', () => {
  it('AC-06: renders every returned finding with severity, category, and observation', async () => {
    useFixtureFindings()

    renderFindings()

    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row')
    // header row + two data rows
    expect(rows).toHaveLength(3)
    expect(table.textContent).toContain('order_date has future dates.')
    expect(table.textContent).toContain(
      'category has inconsistent capitalization.',
    )
    expect(table.textContent).toContain('Critical')
    expect(table.textContent).toContain('Low')
  })

  it("UI-03: shows each finding's persisted review state in a Review column", async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/findings', () =>
        HttpResponse.json(
          makeFindingsListResponse({
            items: [
              { ...FIXTURE_ITEMS[0], review_state: 'needs_investigation' },
              { ...FIXTURE_ITEMS[1], review_state: 'dismissed' },
            ],
          }),
        ),
      ),
    )

    renderFindings()

    const table = await screen.findByRole('table')
    expect(
      within(table).getByRole('columnheader', { name: 'Review' }),
    ).toBeInTheDocument()
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows[0].textContent).toContain('Needs investigation')
    expect(rows[1].textContent).toContain('Dismissed')
  })

  it('AC-06: sorts rendered findings by priority_score descending', async () => {
    useFixtureFindings()

    renderFindings()

    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows[0].textContent).toContain('order_date has future dates.')
    expect(rows[1].textContent).toContain(
      'category has inconsistent capitalization.',
    )
  })

  it('AC-06: severity filter (via URL search parameters) narrows the rendered list', async () => {
    useFixtureFindings()
    const user = userEvent.setup()

    const router = renderFindings()
    await screen.findByRole('table')

    await user.selectOptions(screen.getByLabelText('Severity'), 'critical')

    expect(await screen.findByText('1 of 2 findings')).toBeInTheDocument()
    expect(screen.getByRole('table').textContent).toContain(
      'order_date has future dates.',
    )
    expect(screen.getByRole('table').textContent).not.toContain(
      'category has inconsistent capitalization.',
    )
    expect(router.state.location.search).toContain('severity=critical')
  })

  it('AC-06: reads an initial severity filter from the URL', async () => {
    useFixtureFindings()

    renderFindings('?severity=low')

    expect(await screen.findByText('1 of 2 findings')).toBeInTheDocument()
    expect((screen.getByLabelText('Severity') as HTMLSelectElement).value).toBe(
      'low',
    )
  })

  it('AC-06: search filter matches the observation text', async () => {
    useFixtureFindings()
    const user = userEvent.setup()

    renderFindings()
    await screen.findByRole('table')

    await user.type(screen.getByLabelText('Search'), 'capitalization')

    expect(await screen.findByText('1 of 2 findings')).toBeInTheDocument()
  })

  it('AC-07 (WP-028): links each row observation to its finding-detail URL by finding_id', async () => {
    useFixtureFindings()

    renderFindings()

    const link = await screen.findByRole('link', {
      name: 'order_date has future dates.',
    })
    expect(link).toHaveAttribute('href', `/analyses/${ANALYSIS_ID}/findings/0`)
    const otherLink = screen.getByRole('link', {
      name: 'category has inconsistent capitalization.',
    })
    expect(otherLink).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/findings/1`,
    )
  })

  it('UX-05: review filter (via URL search parameters) narrows to one review state', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/findings', () =>
        HttpResponse.json(
          makeFindingsListResponse({
            items: [
              { ...FIXTURE_ITEMS[0], review_state: 'confirmed' },
              FIXTURE_ITEMS[1],
            ],
          }),
        ),
      ),
    )
    const user = userEvent.setup()

    const router = renderFindings()
    await screen.findByRole('table')

    await user.selectOptions(screen.getByLabelText('Review'), 'unreviewed')

    expect(await screen.findByText('1 of 2 findings')).toBeInTheDocument()
    expect(screen.getByRole('table').textContent).toContain(
      'category has inconsistent capitalization.',
    )
    expect(screen.getByRole('table').textContent).not.toContain(
      'order_date has future dates.',
    )
    expect(router.state.location.search).toContain('review=unreviewed')
  })

  it('UX-05: reads an initial review filter from the URL', async () => {
    useFixtureFindings()

    renderFindings('?review=dismissed')

    expect(
      await screen.findByText('No findings match the current filters.'),
    ).toBeInTheDocument()
    expect((screen.getByLabelText('Review') as HTMLSelectElement).value).toBe(
      'dismissed',
    )
  })

  it('UX-05: shows category and severity in business wording, not raw identifiers', async () => {
    useFixtureFindings()

    renderFindings()

    const table = await screen.findByRole('table')
    expect(table.textContent).toContain('Valid values')
    expect(table.textContent).toContain('Consistency')
    expect(table.textContent).not.toContain('validity')
    const category = screen.getByLabelText('Category') as HTMLSelectElement
    expect(
      Array.from(category.options).map((option) => option.textContent),
    ).toEqual(['All', 'Consistency', 'Valid values'])
    const severity = screen.getByLabelText('Severity') as HTMLSelectElement
    expect(
      Array.from(severity.options).map((option) => option.textContent),
    ).toEqual(['All', 'Critical', 'Low'])
  })

  it('UX-05: links carry the active filters to the finding and offer the first unreviewed finding', async () => {
    useFixtureFindings()

    renderFindings('?severity=low')

    const link = await screen.findByRole('link', {
      name: 'category has inconsistent capitalization.',
    })
    expect(link).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/findings/1?severity=low`,
    )
    expect(
      screen.getByRole('link', { name: 'Review the first unreviewed finding' }),
    ).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/findings/1?severity=low`,
    )
  })

  it('UX-05: when every shown finding is reviewed it says so instead of offering a link', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/findings', () =>
        HttpResponse.json(
          makeFindingsListResponse({
            items: [
              { ...FIXTURE_ITEMS[0], review_state: 'confirmed' },
              { ...FIXTURE_ITEMS[1], review_state: 'dismissed' },
            ],
          }),
        ),
      ),
    )

    renderFindings()

    expect(
      await screen.findByText('Every finding shown has been reviewed.'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('link', {
        name: 'Review the first unreviewed finding',
      }),
    ).toBeNull()
  })

  it('renders a "no findings match" message when filters exclude everything', async () => {
    useFixtureFindings()

    renderFindings('?severity=medium')

    expect(
      await screen.findByText('No findings match the current filters.'),
    ).toBeInTheDocument()
  })
})
