import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, redirect, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it } from 'vitest'
import { server } from '../../test/msw/server'
import { apiErrorBody, DEMO_ANALYSIS_ID } from '../../test/msw/handlers'
import { AnalysisLayoutRoute } from './AnalysisLayoutRoute'
import { StartRoute } from './StartRoute'

function renderStartRoute() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      { path: '/', loader: () => redirect('/analyses/new') },
      { path: '/analyses/new', element: <StartRoute /> },
      {
        path: '/analyses/:analysisId',
        element: <AnalysisLayoutRoute />,
        children: [{ path: 'overview', element: <p>Overview screen</p> }],
      },
    ],
    { initialEntries: ['/'] },
  )

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )

  return router
}

describe('StartRoute', () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  it('AC-01: "/" redirects to "/analyses/new" and renders the Start screen', async () => {
    renderStartRoute()

    expect(
      await screen.findByRole('heading', { name: 'TrustTable' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Try the sales demo' }),
    ).toBeInTheDocument()
  })

  it('AC-01: presents a visibly disabled upload control with explanatory text', async () => {
    renderStartRoute()
    await screen.findByRole('heading', { name: 'TrustTable' })

    const fileInput = screen.getByLabelText('Choose a file to upload')
    expect(fileInput).toBeDisabled()
    expect(
      screen.getByText(/File upload is not available yet/i),
    ).toBeInTheDocument()
  })

  it('AC-01: renders the fixed AI-disabled status', async () => {
    renderStartRoute()
    await screen.findByRole('heading', { name: 'TrustTable' })

    expect(screen.getByText(/AI is disabled/i)).toBeInTheDocument()
  })

  it('AC-02: activating the demo action calls the demo endpoint once and navigates to the overview route', async () => {
    let callCount = 0
    server.use(
      http.post('http://localhost/api/v1/demo/sales', () => {
        callCount += 1
        return HttpResponse.json(
          {
            analysis: {
              analysis_id: DEMO_ANALYSIS_ID,
              state: 'completed',
              dataset: {
                dataset_id: 'd1',
                original_filename: 'sales_demo.csv',
                format: 'csv',
                byte_size: 1,
                content_hash: 'h',
                source_type: 'bundled_demo',
                created_at: '2026-08-30T00:00:00Z',
              },
              security_exposure: {
                model_provider_enabled: false,
                sample_transmission_enabled: false,
              },
              trust_assessment: null,
              finding_count: 0,
              failure: null,
              created_at: '2026-08-30T00:00:00Z',
              started_at: null,
              completed_at: null,
              failed_at: null,
              cancelled_at: null,
            },
            status_url: `/api/v1/analyses/${DEMO_ANALYSIS_ID}/status`,
          },
          { status: 202 },
        )
      }),
    )
    const user = userEvent.setup()
    const router = renderStartRoute()
    await screen.findByRole('heading', { name: 'TrustTable' })

    await user.click(screen.getByRole('button', { name: 'Try the sales demo' }))

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(
        `/analyses/${DEMO_ANALYSIS_ID}/overview`,
      )
    })
    expect(callCount).toBe(1)
  })

  it('renders a safe error message when the demo action fails, without a raw exception', async () => {
    server.use(
      http.post('http://localhost/api/v1/demo/sales', () => {
        return HttpResponse.json(
          apiErrorBody(
            'INTERNAL_ERROR',
            'The demo analysis could not be started.',
          ),
          { status: 500 },
        )
      }),
    )
    const user = userEvent.setup()
    renderStartRoute()
    await screen.findByRole('heading', { name: 'TrustTable' })

    await user.click(screen.getByRole('button', { name: 'Try the sales demo' }))

    expect(
      await screen.findByText('The demo analysis could not be started.'),
    ).toBeInTheDocument()
  })
})
