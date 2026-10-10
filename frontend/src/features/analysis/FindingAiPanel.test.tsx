import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  apiErrorBody,
  makeFindingAiEnrichmentResponse,
  makeFindingExplanationResponse,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { FindingDetailRoute } from './FindingDetailRoute'

const ANALYSIS_ID = 'ai-panel-under-test'
const BASE = 'http://localhost/api/v1/analyses/:analysisId/findings/:findingId'

function renderDetail() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      {
        path: '/analyses/:analysisId/findings/:findingId',
        element: <FindingDetailRoute />,
      },
      { path: '/analyses/:analysisId/findings', element: <p>Findings</p> },
    ],
    { initialEntries: [`/analyses/${ANALYSIS_ID}/findings/0`] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

const AI_EXPLANATION = makeFindingExplanationResponse({
  narrative: 'The AI says two dates lie in the future.',
  provenance: 'ai_interpretation',
  provider_name: 'mock',
  ai_provenance: {
    deployment_label: 'Test AI',
    runtime_label: 'Mock provider',
    model_label: 'mock-v1',
    quantization: null,
    model_identifier: 'mock-v1',
  },
  ai_call_status: 'attempted_accepted',
  evidence_sent_to_model: true,
})

/** Serve the enrichment status from a script of states, counting every start. */
function scriptEnrichment(
  states: ReturnType<typeof makeFindingAiEnrichmentResponse>[],
) {
  const calls = { posts: 0, gets: 0 }
  let index = 0
  server.use(
    http.get(`${BASE}/ai-enrichment`, () => {
      calls.gets += 1
      const state = states[Math.min(index, states.length - 1)]
      index += 1
      return HttpResponse.json(state)
    }),
    http.post(`${BASE}/ai-enrichment`, () => {
      calls.posts += 1
      return HttpResponse.json(
        makeFindingAiEnrichmentResponse({
          state: 'preparing',
          poll_interval_ms: 20,
        }),
        { status: 202 },
      )
    }),
  )
  return calls
}

describe('FindingAiPanel (UX-05b)', () => {
  it('shows nothing and requests nothing when no AI is configured', async () => {
    const calls = scriptEnrichment([
      makeFindingAiEnrichmentResponse({ state: 'unavailable' }),
    ])

    renderDetail()

    expect(
      await screen.findByRole('heading', { name: 'Explanation' }),
    ).toBeInTheDocument()
    await waitFor(() => {
      expect(calls.gets).toBeGreaterThan(0)
    })
    expect(screen.queryByText(/AI explanation: preparing/)).toBeNull()
    expect(calls.posts).toBe(0)
  })

  it('opening a finding requests its AI explanation once, and the built-in guidance is already on the page', async () => {
    const calls = scriptEnrichment([
      makeFindingAiEnrichmentResponse({ state: 'not_requested' }),
      makeFindingAiEnrichmentResponse({
        state: 'preparing',
        poll_interval_ms: 1_000_000,
      }),
    ])

    renderDetail()

    expect(
      await screen.findByText(/AI explanation: preparing/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Possible business impact' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Built-in TrustTable guidance \(no AI\)/),
    ).toBeInTheDocument()
    await waitFor(() => {
      expect(calls.posts).toBe(1)
    })
    // Never again for the same finding and state.
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(calls.posts).toBe(1)
  })

  it('polls while preparing, then reads the explanation again and shows the AI result', async () => {
    let explanationReads = 0
    server.use(
      http.get(`${BASE}/explanation`, () => {
        explanationReads += 1
        return HttpResponse.json(
          explanationReads === 1
            ? makeFindingExplanationResponse({
                ai_call_status: 'not_attempted',
              })
            : AI_EXPLANATION,
        )
      }),
    )
    scriptEnrichment([
      makeFindingAiEnrichmentResponse({
        state: 'preparing',
        poll_interval_ms: 20,
      }),
      makeFindingAiEnrichmentResponse({
        state: 'preparing',
        poll_interval_ms: 20,
      }),
      makeFindingAiEnrichmentResponse({ state: 'ready' }),
    ])

    renderDetail()

    expect(
      await screen.findByText(/AI explanation: preparing/),
    ).toBeInTheDocument()
    expect(
      await screen.findByText('The AI says two dates lie in the future.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('AI interpretation — Test AI · Mock provider · mock-v1'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/AI explanation: preparing/)).toBeNull()
    expect(explanationReads).toBeGreaterThanOrEqual(2)
  })

  it('a failed enrichment keeps the guidance, says so, and is retried only when asked', async () => {
    const calls = scriptEnrichment([
      makeFindingAiEnrichmentResponse({
        state: 'failed',
        reason: 'provider_error',
      }),
    ])
    const user = userEvent.setup()

    renderDetail()

    expect(
      await screen.findByText(/The AI explanation could not be completed/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Remediation' }),
    ).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(calls.posts).toBe(0)

    await user.click(
      screen.getByRole('button', { name: 'Try AI explanation again' }),
    )

    await waitFor(() => {
      expect(calls.posts).toBe(1)
    })
    expect(
      await screen.findByText(/AI explanation: preparing/),
    ).toBeInTheDocument()
  })

  it('a busy refusal is explained, is not retried in a loop, and can be asked again', async () => {
    let posts = 0
    server.use(
      http.get(`${BASE}/ai-enrichment`, () =>
        HttpResponse.json(
          makeFindingAiEnrichmentResponse({ state: 'not_requested' }),
        ),
      ),
      http.post(`${BASE}/ai-enrichment`, () => {
        posts += 1
        return HttpResponse.json(
          apiErrorBody(
            'AI_ENRICHMENT_BUSY',
            'AI explanations are busy right now. Try again shortly.',
          ),
          { status: 429 },
        )
      }),
    )
    const user = userEvent.setup()

    renderDetail()

    expect(
      await screen.findByText(/AI explanations are busy right now/),
    ).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(posts).toBe(1)

    await user.click(
      screen.getByRole('button', { name: 'Try AI explanation again' }),
    )
    await waitFor(() => {
      expect(posts).toBe(2)
    })
  })

  it('a stale result is requested again under the new binding, once', async () => {
    const calls = scriptEnrichment([
      makeFindingAiEnrichmentResponse({ state: 'stale' }),
      makeFindingAiEnrichmentResponse({
        state: 'preparing',
        poll_interval_ms: 1_000_000,
      }),
    ])

    renderDetail()

    expect(
      await screen.findByText(/AI explanation: preparing/),
    ).toBeInTheDocument()
    await waitFor(() => {
      expect(calls.posts).toBe(1)
    })
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(calls.posts).toBe(1)
  })

  it('renders a saved AI narrative as text, never as markup', async () => {
    server.use(
      http.get(`${BASE}/explanation`, () =>
        HttpResponse.json({
          ...AI_EXPLANATION,
          narrative: '<img src="x" onerror="alert(1)"> <b>bold</b>',
        }),
      ),
    )
    scriptEnrichment([makeFindingAiEnrichmentResponse({ state: 'ready' })])

    renderDetail()

    expect(
      await screen.findByText('<img src="x" onerror="alert(1)"> <b>bold</b>'),
    ).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    expect(document.querySelector('b')).toBeNull()
  })

  it('the deterministic page does not wait for the AI status', async () => {
    server.use(
      http.get(`${BASE}/ai-enrichment`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 3000))
        return HttpResponse.json(makeFindingAiEnrichmentResponse())
      }),
    )

    renderDetail()

    expect(
      await screen.findByRole(
        'heading',
        { name: 'Explanation' },
        { timeout: 1500 },
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Remediation' }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/AI explanation: preparing/)).toBeNull()
  })
})
