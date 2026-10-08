import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeAiStatusResponse } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { AiStatusPanel } from './AiStatusPanel'

const URL = 'http://localhost/api/v1/ai/status'

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <AiStatusPanel />
    </QueryClientProvider>,
  )
}

describe('AiStatusPanel', () => {
  it('shows a polite loading state first', async () => {
    renderPanel()

    expect(screen.getByRole('status')).toHaveTextContent(
      'Checking the Local AI status…',
    )
    await screen.findByText('AI assistance: off')
  })

  it('shows AI assistance as off with the server summary', async () => {
    renderPanel()

    expect(await screen.findByText('AI assistance: off')).toBeInTheDocument()
    expect(screen.getByText(/built-in checks only/)).toBeInTheDocument()
    expect(screen.queryByText(/Runtime:/)).not.toBeInTheDocument()
  })

  it('shows a ready runtime with its model', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json(
          makeAiStatusResponse({
            assistance: 'on',
            state: 'ready',
            location: 'local',
            provider_label: 'Local AI',
            runtime_label: 'llama.cpp',
            model_label: 'Qwen3.5 4B',
            summary:
              'AI assistance is on and the llama.cpp runtime is ready, on this machine.',
          }),
        ),
      ),
    )
    renderPanel()

    expect(
      await screen.findByText('AI assistance: on and ready'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Runtime: llama.cpp · Model: Qwen3.5 4B'),
    ).toBeInTheDocument()
  })

  it('shows an unreachable runtime as a warning in words, not only by colour', async () => {
    server.use(
      http.get(URL, () =>
        HttpResponse.json(
          makeAiStatusResponse({
            assistance: 'on',
            state: 'unavailable',
            location: 'local',
            runtime_label: 'llama.cpp',
            model_label: null,
            summary:
              'AI assistance is turned on, but the llama.cpp runtime is not reachable right now. Everything else works with the built-in checks alone.',
          }),
        ),
      ),
    )
    renderPanel()

    expect(
      await screen.findByText('AI assistance: on, not reachable'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Everything else works with the built-in checks alone/),
    ).toBeInTheDocument()
    expect(screen.getByText('Runtime: llama.cpp')).toBeInTheDocument()
  })

  it('says the status is unavailable, and that the checks do not depend on it, when the route fails', async () => {
    server.use(http.get(URL, () => HttpResponse.json({}, { status: 500 })))
    renderPanel()

    expect(
      await screen.findByText('Local AI status is not available'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/do not depend on AI and are unaffected/),
    ).toBeInTheDocument()
  })
})
