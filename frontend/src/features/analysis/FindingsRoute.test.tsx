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
  },
  {
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

  it('renders a "no findings match" message when filters exclude everything', async () => {
    useFixtureFindings()

    renderFindings('?severity=medium')

    expect(
      await screen.findByText('No findings match the current filters.'),
    ).toBeInTheDocument()
  })
})
