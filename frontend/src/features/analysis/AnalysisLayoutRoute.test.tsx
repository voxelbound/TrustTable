import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  makeAnalysisResource,
  makeStatusResponse,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { AnalysisLayoutRoute } from './AnalysisLayoutRoute'

const ANALYSIS_ID = 'analysis-under-test'

function renderLayout(initialPath = `/analyses/${ANALYSIS_ID}/overview`) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      {
        path: '/analyses/:analysisId',
        element: <AnalysisLayoutRoute />,
        children: [{ path: 'overview', element: <p>Overview screen</p> }],
      },
      { path: '/analyses/new', element: <p>Start screen</p> },
    ],
    { initialEntries: [initialPath] },
  )

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )

  return router
}

describe('AnalysisLayoutRoute', () => {
  it('AC-03: renders the named stage while in progress', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/status', () =>
        HttpResponse.json(
          makeStatusResponse({ state: 'validating', cancellable: true }),
        ),
      ),
    )

    renderLayout()

    expect(
      await screen.findByText('Validating the dataset.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Overview screen')).not.toBeInTheDocument()
  })

  it('AC-03: polls across multiple in-progress states and stops once completed', async () => {
    // Real timers, not fake ones: MSW's Node request interception
    // schedules its own internal async work, which does not reliably
    // advance under `vi.useFakeTimers()` — a fake-timer version of
    // this test hung indefinitely rather than failing a specific
    // assertion. `waitFor`'s generous timeouts tolerate the real
    // 1-second poll interval instead.
    let callCount = 0
    const sequence = ['queued', 'validating', 'completed']
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/status', () => {
        const state = sequence[Math.min(callCount, sequence.length - 1)]
        callCount += 1
        return HttpResponse.json(
          makeStatusResponse({ state, cancellable: state === 'queued' }),
        )
      }),
    )

    renderLayout()

    expect(await screen.findByText('Analysis is queued.')).toBeInTheDocument()
    expect(callCount).toBe(1)

    await waitFor(() => expect(callCount).toBeGreaterThanOrEqual(2), {
      timeout: 3000,
    })
    expect(
      await screen.findByText('Validating the dataset.'),
    ).toBeInTheDocument()

    await waitFor(() => expect(callCount).toBeGreaterThanOrEqual(3), {
      timeout: 3000,
    })
    expect(await screen.findByText('Overview screen')).toBeInTheDocument()

    // Polling must not continue once a terminal state has been observed.
    const stableCallCount = callCount
    await new Promise((resolve) => setTimeout(resolve, 2500))
    expect(callCount).toBe(stableCallCount)
  }, 10_000)

  it('AC-04: renders a safe failure message derived from AnalysisFailureResponse, never a raw exception', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/status', () =>
        HttpResponse.json(
          makeStatusResponse({ state: 'failed', cancellable: false }),
        ),
      ),
      http.get('http://localhost/api/v1/analyses/:analysisId', () =>
        HttpResponse.json(
          makeAnalysisResource({
            state: 'failed',
            failure: {
              code: 'INTERNAL_ERROR',
              message: 'The dataset could not be parsed.',
            },
            trust_assessment: null,
          }),
        ),
      ),
    )

    renderLayout()

    expect(
      await screen.findByText('The dataset could not be parsed.'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Traceback/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/at\s+\w+\.\w+\s*\(/)).not.toBeInTheDocument()
  })

  it('AC-04: "Return to start" navigates to /analyses/new from a failed analysis', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/status', () =>
        HttpResponse.json(
          makeStatusResponse({ state: 'failed', cancellable: false }),
        ),
      ),
      http.get('http://localhost/api/v1/analyses/:analysisId', () =>
        HttpResponse.json(
          makeAnalysisResource({
            state: 'failed',
            failure: { code: 'INTERNAL_ERROR', message: 'Failed.' },
            trust_assessment: null,
          }),
        ),
      ),
    )
    const user = userEvent.setup()

    const router = renderLayout()
    await screen.findByRole('button', { name: 'Return to start' })
    await user.click(screen.getByRole('button', { name: 'Return to start' }))

    expect(router.state.location.pathname).toBe('/analyses/new')
  })

  it('renders a cancelled analysis with no results and a return-to-start action', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/status', () =>
        HttpResponse.json(
          makeStatusResponse({ state: 'cancelled', cancellable: false }),
        ),
      ),
    )

    renderLayout()

    expect(
      await screen.findByText('This analysis was cancelled'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Return to start' }),
    ).toBeInTheDocument()
  })

  it('renders a safe message when the status request itself fails (unknown analysis)', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/status', () =>
        HttpResponse.json(
          {
            error: {
              code: 'ANALYSIS_NOT_FOUND',
              message: 'The requested analysis was not found.',
              details: {},
              request_id: 'req-1',
            },
          },
          { status: 404 },
        ),
      ),
    )

    renderLayout()

    expect(
      await screen.findByText('The requested analysis was not found.'),
    ).toBeInTheDocument()
  })
})
