import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { FindingNavigation } from '../../domain/findingNavigation'
import { makeFindingsListResponse } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { FindingDetailRoute } from './FindingDetailRoute'
import { FindingNavigator } from './FindingNavigator'

const ANALYSIS_ID = 'navigation-under-test'

function item(
  id: string,
  priority: number,
  reviewState: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    finding_id: id,
    detector_id: 'validity.future_dates',
    detector_version: '1.0.0',
    category: 'validity',
    severity: 'medium',
    confidence: 0.9,
    priority_score: priority,
    calculated_observation: `Finding ${id}.`,
    affected_columns: [],
    affected_row_count: 1,
    evidence_count: 1,
    review_state: reviewState,
    note: null,
    dismissal_reason: null,
    reviewed_at: null,
    ...overrides,
  }
}

// Priority order: 0 (unreviewed), 1 (confirmed), 2 (unreviewed).
const ITEMS = [
  item('2', 20, 'unreviewed', { severity: 'low' }),
  item('0', 90, 'unreviewed', { severity: 'critical' }),
  item('1', 50, 'confirmed'),
]

function useFixtureFindings() {
  server.use(
    http.get('http://localhost/api/v1/analyses/:analysisId/findings', () =>
      HttpResponse.json(makeFindingsListResponse({ items: ITEMS })),
    ),
  )
}

function renderDetail(findingId: string, search = '') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      {
        path: '/analyses/:analysisId/findings/:findingId',
        element: <FindingDetailRoute />,
      },
    ],
    {
      initialEntries: [
        `/analyses/${ANALYSIS_ID}/findings/${findingId}${search}`,
      ],
    },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

describe('finding detail navigation', () => {
  it('shows the position and links previous and next in priority order', async () => {
    useFixtureFindings()

    renderDetail('1')

    const nav = await screen.findByRole('navigation', {
      name: 'Move between findings',
    })
    expect(nav.textContent).toContain('Finding 2 of 3 in this analysis.')
    expect(screen.getByRole('link', { name: 'Previous' })).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/findings/0`,
    )
    expect(screen.getByRole('link', { name: 'Next' })).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/findings/2`,
    )
  })

  it('next-unreviewed skips the reviewed finding between', async () => {
    useFixtureFindings()

    renderDetail('0')

    expect(
      await screen.findByRole('link', { name: 'Next unreviewed' }),
    ).toHaveAttribute('href', `/analyses/${ANALYSIS_ID}/findings/2`)
  })

  it('follows the active filters and carries them in every link', async () => {
    useFixtureFindings()

    renderDetail('0', '?review=unreviewed')

    const nav = await screen.findByRole('navigation', {
      name: 'Move between findings',
    })
    expect(nav.textContent).toContain('Finding 1 of 2 in the filtered list.')
    // The confirmed finding is filtered out, so its neighbour is finding 2.
    expect(screen.getByRole('link', { name: 'Next' })).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/findings/2?review=unreviewed`,
    )
    expect(
      screen.getByRole('link', { name: '← Back to findings' }),
    ).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/findings?review=unreviewed`,
    )
  })

  it('says so and offers no wrap-around at the last finding', async () => {
    useFixtureFindings()

    renderDetail('2')

    const nav = await screen.findByRole('navigation', {
      name: 'Move between findings',
    })
    expect(screen.queryByRole('link', { name: 'Next' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Next unreviewed' })).toBeNull()
    expect(nav.textContent).toContain('This is the last finding')
    expect(nav.textContent).toContain('No unreviewed finding follows.')
  })

  it('a finding the filters exclude has no position but still offers next-unreviewed', async () => {
    useFixtureFindings()

    renderDetail('1', '?review=unreviewed')

    const nav = await screen.findByRole('navigation', {
      name: 'Move between findings',
    })
    expect(nav.textContent).toContain(
      'This finding is not in the list the filters show (2 findings shown).',
    )
    expect(
      screen.getByRole('link', { name: 'Next unreviewed' }),
    ).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/findings/0?review=unreviewed`,
    )
  })

  it('shows the category in business wording, not the raw identifier', async () => {
    useFixtureFindings()

    renderDetail('0')

    await screen.findByRole('navigation', { name: 'Move between findings' })
    expect(screen.getByText('Valid values')).toBeInTheDocument()
    expect(screen.queryByText('validity')).toBeNull()
  })

  it('still renders the finding when the list cannot be loaded', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/findings', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderDetail('0')

    expect(
      await screen.findByRole('heading', { name: 'Observation' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('navigation', { name: 'Move between findings' }),
    ).toBeNull()
  })

  it('keyboard: n, p and u move between findings', async () => {
    useFixtureFindings()
    const user = userEvent.setup()

    const router = renderDetail('1')
    await screen.findByRole('navigation', { name: 'Move between findings' })

    await user.keyboard('n')
    expect(router.state.location.pathname).toBe(
      `/analyses/${ANALYSIS_ID}/findings/2`,
    )
    await screen.findByText('Finding 3 of 3 in this analysis.')

    await user.keyboard('p')
    expect(router.state.location.pathname).toBe(
      `/analyses/${ANALYSIS_ID}/findings/1`,
    )
    await screen.findByText('Finding 2 of 3 in this analysis.')

    await user.keyboard('p')
    await screen.findByText('Finding 1 of 3 in this analysis.')
    await user.keyboard('u')
    expect(router.state.location.pathname).toBe(
      `/analyses/${ANALYSIS_ID}/findings/2`,
    )
  })

  it('keyboard: a shortcut does nothing past the end of the list', async () => {
    useFixtureFindings()
    const user = userEvent.setup()

    const router = renderDetail('2')
    await screen.findByRole('navigation', { name: 'Move between findings' })

    await user.keyboard('n')
    await user.keyboard('u')

    expect(router.state.location.pathname).toBe(
      `/analyses/${ANALYSIS_ID}/findings/2`,
    )
  })
})

describe('FindingNavigator shortcuts', () => {
  const NAVIGATION: FindingNavigation = {
    position: 1,
    total: 3,
    previousId: null,
    nextId: '1',
    nextUnreviewedId: '1',
  }

  function renderNavigator() {
    const router = createMemoryRouter(
      [
        {
          path: '/analyses/:analysisId/findings/:findingId',
          element: (
            <>
              <label>
                Note
                <input />
              </label>
              <FindingNavigator
                analysisId={ANALYSIS_ID}
                navigation={NAVIGATION}
                search=""
                filtered={false}
              />
            </>
          ),
        },
      ],
      { initialEntries: [`/analyses/${ANALYSIS_ID}/findings/0`] },
    )
    render(<RouterProvider router={router} />)
    return router
  }

  it('does not fire while typing in a field', async () => {
    const user = userEvent.setup()
    const router = renderNavigator()

    await user.type(screen.getByLabelText('Note'), 'nun')

    expect(router.state.location.pathname).toBe(
      `/analyses/${ANALYSIS_ID}/findings/0`,
    )
    expect(screen.getByLabelText('Note')).toHaveValue('nun')
  })

  it('does not fire with a modifier key held', async () => {
    const user = userEvent.setup()
    const router = renderNavigator()

    await user.keyboard('{Control>}n{/Control}')

    expect(router.state.location.pathname).toBe(
      `/analyses/${ANALYSIS_ID}/findings/0`,
    )
  })

  it('fires when focus is on the page, and states the shortcuts', async () => {
    const user = userEvent.setup()
    const router = renderNavigator()

    expect(
      screen.getByText(/Keyboard: P previous, N next, U next unreviewed\./),
    ).toBeInTheDocument()
    await user.keyboard('n')

    expect(router.state.location.pathname).toBe(
      `/analyses/${ANALYSIS_ID}/findings/1`,
    )
  })
})
