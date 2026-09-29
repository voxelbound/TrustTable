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

function useStatus(overrides: Parameters<typeof makeStatusResponse>[0]) {
  server.use(
    http.get('http://localhost/api/v1/analyses/:analysisId/status', () =>
      HttpResponse.json(makeStatusResponse(overrides)),
    ),
    http.get('http://localhost/api/v1/analyses/:analysisId', () =>
      HttpResponse.json(
        makeAnalysisResource({
          state: overrides?.state ?? 'completed',
          failure:
            overrides?.state === 'failed'
              ? { code: 'INTERNAL_ERROR', message: 'Failed.' }
              : null,
          trust_assessment: null,
        }),
      ),
    ),
  )
}

function renderLayout() {
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
    { initialEntries: [`/analyses/${ANALYSIS_ID}/overview`] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const errorBody = (code: string, message: string) => ({
  error: { code, message, details: {}, request_id: 'req-1' },
})

describe('AnalysisActions', () => {
  it('offers cancel only while the API says the analysis is cancellable', async () => {
    useStatus({ state: 'validating', cancellable: true, retryable: false })
    renderLayout()

    expect(
      await screen.findByRole('button', { name: 'Cancel analysis' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Retry analysis' }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Delete analysis' }),
    ).toBeInTheDocument()
  })

  it('cancel calls POST cancel and then shows the cancelled state', async () => {
    let cancelled = false
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/status', () =>
        HttpResponse.json(
          makeStatusResponse(
            cancelled
              ? { state: 'cancelled', cancellable: false, retryable: false }
              : { state: 'validating', cancellable: true, retryable: false },
          ),
        ),
      ),
      http.get('http://localhost/api/v1/analyses/:analysisId', () =>
        HttpResponse.json(
          makeAnalysisResource({ state: 'cancelled', trust_assessment: null }),
        ),
      ),
      http.post('http://localhost/api/v1/analyses/:analysisId/cancel', () => {
        cancelled = true
        return HttpResponse.json(
          makeAnalysisResource({ state: 'cancelled', trust_assessment: null }),
        )
      }),
    )
    const user = userEvent.setup()
    renderLayout()

    await user.click(
      await screen.findByRole('button', { name: 'Cancel analysis' }),
    )

    expect(
      await screen.findByText('This analysis was cancelled'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Cancel analysis' }),
    ).not.toBeInTheDocument()
  })

  it('offers retry only for a failed analysis and navigates to the new attempt', async () => {
    useStatus({ state: 'failed', cancellable: false, retryable: true })
    server.use(
      http.post('http://localhost/api/v1/analyses/:analysisId/retry', () =>
        HttpResponse.json(
          {
            analysis: makeAnalysisResource({
              analysis_id: 'new-attempt',
              state: 'queued',
              trust_assessment: null,
            }),
            retry_source_analysis_id: ANALYSIS_ID,
            status_url: '/api/v1/analyses/new-attempt/status',
          },
          { status: 202 },
        ),
      ),
    )
    const user = userEvent.setup()
    const router = renderLayout()

    expect(
      screen.queryByRole('button', { name: 'Cancel analysis' }),
    ).not.toBeInTheDocument()
    await user.click(
      await screen.findByRole('button', { name: 'Retry analysis' }),
    )

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/analyses/new-attempt'),
    )
  })

  it('shows an inline error and stays on the page when retry fails', async () => {
    useStatus({ state: 'failed', cancellable: false, retryable: true })
    server.use(
      http.post('http://localhost/api/v1/analyses/:analysisId/retry', () =>
        HttpResponse.json(
          errorBody(
            'ANALYSIS_NOT_RETRYABLE',
            'Only a failed analysis can be retried.',
          ),
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    const router = renderLayout()

    await user.click(
      await screen.findByRole('button', { name: 'Retry analysis' }),
    )

    expect(
      await screen.findByText('Only a failed analysis can be retried.'),
    ).toBeInTheDocument()
    expect(router.state.location.pathname).toBe(
      `/analyses/${ANALYSIS_ID}/overview`,
    )
  })

  it('delete asks for confirmation and sends no request when the dialog is cancelled', async () => {
    useStatus({ state: 'completed', cancellable: false, retryable: false })
    let deleteCalls = 0
    server.use(
      http.delete('http://localhost/api/v1/analyses/:analysisId', () => {
        deleteCalls += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderLayout()

    await user.click(
      await screen.findByRole('button', { name: 'Delete analysis' }),
    )
    const dialog = await screen.findByRole('alertdialog', {
      name: 'Delete this analysis?',
    })
    expect(dialog).toHaveAccessibleDescription(/cannot be undone/i)
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(deleteCalls).toBe(0)
  })

  it('Escape closes the delete dialog without deleting', async () => {
    useStatus({ state: 'completed', cancellable: false, retryable: false })
    let deleteCalls = 0
    server.use(
      http.delete('http://localhost/api/v1/analyses/:analysisId', () => {
        deleteCalls += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderLayout()

    await user.click(
      await screen.findByRole('button', { name: 'Delete analysis' }),
    )
    await screen.findByRole('alertdialog')
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(deleteCalls).toBe(0)
  })

  it('confirming delete calls DELETE once and returns to the start screen', async () => {
    useStatus({ state: 'completed', cancellable: false, retryable: false })
    let deleteCalls = 0
    server.use(
      http.delete('http://localhost/api/v1/analyses/:analysisId', () => {
        deleteCalls += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    const router = renderLayout()

    await user.click(
      await screen.findByRole('button', { name: 'Delete analysis' }),
    )
    await user.click(
      await screen.findByRole('button', { name: 'Delete permanently' }),
    )

    await waitFor(() =>
      expect(router.state.location.pathname).toBe('/analyses/new'),
    )
    expect(deleteCalls).toBe(1)
    expect(await screen.findByText('Start screen')).toBeInTheDocument()
  })

  it('a failed delete keeps the analysis on screen with an inline error', async () => {
    useStatus({ state: 'completed', cancellable: false, retryable: false })
    server.use(
      http.delete('http://localhost/api/v1/analyses/:analysisId', () =>
        HttpResponse.json(
          errorBody('INTERNAL_ERROR', 'The analysis could not be deleted.'),
          { status: 500 },
        ),
      ),
    )
    const user = userEvent.setup()
    const router = renderLayout()

    await user.click(
      await screen.findByRole('button', { name: 'Delete analysis' }),
    )
    await user.click(
      await screen.findByRole('button', { name: 'Delete permanently' }),
    )

    expect(
      await screen.findByText('The analysis could not be deleted.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe(
      `/analyses/${ANALYSIS_ID}/overview`,
    )
  })
})
