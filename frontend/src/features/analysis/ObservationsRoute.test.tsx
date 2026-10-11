import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/msw/server'
import { ObservationsRoute } from './ObservationsRoute'

const ANALYSIS_ID = 'observations-under-test'

function renderObservations() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      {
        path: '/analyses/:analysisId/observations',
        element: <ObservationsRoute />,
      },
    ],
    { initialEntries: [`/analyses/${ANALYSIS_ID}/observations`] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('ObservationsRoute', () => {
  it('UX-07: says an observation is not a finding, and what to do next', async () => {
    renderObservations()

    expect(
      await screen.findByRole('heading', { name: 'Observations' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Review')).toBeInTheDocument()
    expect(
      screen.getByText(/They are not findings: they have no severity/),
    ).toBeInTheDocument()
    expect(screen.getByText('Next step')).toBeInTheDocument()
  })

  it('UX-07: lists the observations read-only and links example rows to the inspector', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/observations',
        () =>
          HttpResponse.json({
            items: [
              {
                observation_id: 'obs-1',
                summary: 'Most values in this column repeat.',
                affected_row_numbers: [2, 5],
              },
            ],
            total_items: 1,
          }),
      ),
    )
    renderObservations()

    expect(
      await screen.findByText('Most values in this column repeat.'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /Inspect the example rows/ }),
    ).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/observations/obs-1/inspector`,
    )
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('UX-07: states an empty list plainly, not as a failure', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/observations',
        () => HttpResponse.json({ items: [], total_items: 0 }),
      ),
    )
    renderObservations()

    expect(
      await screen.findByText('No observations were recorded.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
