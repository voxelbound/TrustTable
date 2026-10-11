import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  makeAiReadinessResponse,
  makeConnectionTestResponse,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { LocalAiRoute } from './LocalAiRoute'

const READINESS = 'http://localhost/api/v1/ai/readiness'
const TEST = 'http://localhost/api/v1/ai/connection-test'

function renderScreen() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/local-ai']}>
        <LocalAiRoute />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function readyResponse() {
  const base = makeAiReadinessResponse()
  return makeAiReadinessResponse({
    ready: true,
    model_label: 'Qwen3.5 4B',
    runtime_label: 'llama.cpp',
    checks: base.checks.map((check) => ({
      ...check,
      state: 'done' as const,
      detail: `${check.title}.`,
    })),
  })
}

describe('LocalAiRoute', () => {
  it('UX-09: with assistance off, only the first step is open and the rest are not checked yet', async () => {
    renderScreen()

    const section = (
      await screen.findByRole('heading', { name: 'Is it ready?' })
    ).closest('section') as HTMLElement
    const list = await within(section).findByRole('list')
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(5)
    expect(items[0]).toHaveTextContent('AI assistance is on')
    expect(items[0]).toHaveTextContent('To do')
    for (const item of items.slice(1)) {
      expect(item).toHaveTextContent('Not checked yet')
    }
    // A step to do: AI assistance is unavailable, said with the server's own
    // sentence (so "AI" keeps its capitals) and nothing is called a failure.
    const summary = screen.getByText(/AI assistance is not available yet\./)
    expect(summary).toHaveTextContent(
      'AI assistance is not available yet. AI assistance is off. You can turn it on in Settings.',
    )
    expect(summary).toHaveTextContent('built-in checks alone')
    expect(screen.queryByText(/cannot work yet/)).toBeNull()
    expect(screen.queryByText(/not fully confirmed/)).toBeNull()
  })

  it('UX-09: a ready runtime is stated without claiming the model was tested', async () => {
    server.use(http.get(READINESS, () => HttpResponse.json(readyResponse())))
    renderScreen()

    expect(await screen.findByText(/Every step below is done/)).toBeVisible()
    expect(
      screen.getByText(/does not test the model or the quality/),
    ).toBeVisible()
    expect(screen.getByText(/Model named: Qwen3.5 4B/)).toBeVisible()
    expect(screen.getAllByText('Done')).toHaveLength(5)
  })

  it.each([
    [
      'runtime_on_this_machine',
      'TrustTable cannot confirm that the runtime is on this machine.',
    ],
    ['model_named', 'No model name is available to show.'],
  ] as const)(
    'UX-09: an attention-only step (%s) is named, not passed, and is not called a failure',
    async (key, detail) => {
      const base = readyResponse()
      server.use(
        http.get(READINESS, () =>
          HttpResponse.json({
            ...base,
            ready: false,
            checks: base.checks.map((check) =>
              check.key === key
                ? { ...check, state: 'attention', detail }
                : check,
            ),
          }),
        ),
      )
      renderScreen()

      expect(await screen.findByText('Needs attention')).toBeVisible()
      expect(screen.queryByText(/Every step below is done/)).toBeNull()
      // The runtime may answer and AI assistance may work: nothing says it cannot.
      const summary = screen.getByText(
        /Local AI readiness is not fully confirmed/,
      )
      expect(summary).toHaveTextContent(detail)
      expect(summary).toHaveTextContent('This is not a failure')
      expect(summary).toHaveTextContent('AI assistance may still work')
      expect(screen.queryByText(/not available yet/)).toBeNull()
      expect(screen.queryByText(/cannot work/)).toBeNull()
    },
  )

  it('UX-09: a step to do outranks one that needs attention and is called unavailable', async () => {
    const base = readyResponse()
    server.use(
      http.get(READINESS, () =>
        HttpResponse.json({
          ...base,
          ready: false,
          checks: base.checks.map((check) =>
            check.key === 'runtime_on_this_machine'
              ? { ...check, state: 'attention', detail: 'Cannot confirm.' }
              : check.key === 'runtime_answers'
                ? {
                    ...check,
                    state: 'todo',
                    detail: 'The runtime did not answer a short check.',
                  }
                : check,
          ),
        }),
      ),
    )
    renderScreen()

    const summary = await screen.findByText(
      /AI assistance is not available yet/,
    )
    expect(summary).toHaveTextContent(
      'The runtime did not answer a short check.',
    )
    expect(screen.queryByText(/not fully confirmed/)).toBeNull()
  })

  it('UX-09: a readiness failure says AI is unaffected and still offers the test', async () => {
    server.use(
      http.get(READINESS, () =>
        HttpResponse.json(
          {
            error: {
              code: 'INTERNAL',
              message: 'Something went wrong.',
              details: {},
              request_id: 'r',
            },
          },
          { status: 500 },
        ),
      ),
    )
    renderScreen()

    expect(
      await screen.findByText('Local AI could not be checked'),
    ).toBeVisible()
    expect(screen.getByText(/do not depend on AI/)).toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Test connection' }),
    ).toBeEnabled()
  })

  it('UX-09: Test connection sends no body and no input, shows a pending state, then the answer', async () => {
    const user = userEvent.setup()
    let seenBody: string | null = null
    let seenQuery = ''
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.post(TEST, async ({ request }) => {
        seenBody = await request.text()
        seenQuery = new URL(request.url).search
        await gate
        return HttpResponse.json(makeConnectionTestResponse())
      }),
    )
    renderScreen()

    const button = await screen.findByRole('button', {
      name: 'Test connection',
    })
    await user.click(button)

    expect(await screen.findByText('Testing the connection…')).toBeVisible()
    expect(button).toBeDisabled()
    release()

    expect(await screen.findByText('The runtime answered')).toBeVisible()
    expect(screen.getByText(/does not check the model/)).toBeVisible()
    expect(seenBody).toBe('')
    expect(seenQuery).toBe('')
    await waitFor(() => expect(button).toBeEnabled())
  })

  it('UX-09: a successful test refreshes the checklist so it cannot contradict the answer', async () => {
    const user = userEvent.setup()
    let reads = 0
    server.use(
      http.get(READINESS, () => {
        reads += 1
        return HttpResponse.json(
          reads === 1 ? makeAiReadinessResponse() : readyResponse(),
        )
      }),
    )
    renderScreen()
    await screen.findByText(/AI assistance is not available yet/)

    await user.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(await screen.findByText(/Every step below is done/)).toBeVisible()
    expect(reads).toBe(2)
  })

  it.each([
    ['not_reachable', 'The runtime did not answer'],
    ['assistance_off', 'Nothing was tested'],
    ['no_runtime', 'Nothing was tested'],
    ['not_local', 'Nothing was tested'],
    ['busy', 'Nothing was tested'],
  ] as const)(
    'UX-09: the %s outcome is shown in its own words',
    async (outcome, title) => {
      const user = userEvent.setup()
      server.use(
        http.post(TEST, () =>
          HttpResponse.json(
            makeConnectionTestResponse({
              outcome,
              tested: outcome === 'not_reachable',
              message: `Fixed wording for ${outcome}.`,
            }),
          ),
        ),
      )
      renderScreen()

      await user.click(
        await screen.findByRole('button', { name: 'Test connection' }),
      )

      expect(await screen.findByText(title)).toBeVisible()
      expect(screen.getByText(`Fixed wording for ${outcome}.`)).toBeVisible()
    },
  )

  it('UX-09: a test refused as too soon says when to try again and does not refresh the checklist', async () => {
    const user = userEvent.setup()
    let reads = 0
    server.use(
      http.get(READINESS, () => {
        reads += 1
        return HttpResponse.json(makeAiReadinessResponse())
      }),
      http.post(TEST, () =>
        HttpResponse.json(
          makeConnectionTestResponse({
            outcome: 'too_soon',
            tested: false,
            message: 'A test finished a moment ago, so nothing was tested.',
            retry_after_seconds: 4,
          }),
        ),
      ),
    )
    renderScreen()
    await screen.findByText(/AI assistance is not available yet/)

    await user.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(
      await screen.findByText(/Try again in about 4 seconds/),
    ).toBeVisible()
    expect(reads).toBe(1)
  })

  it('UX-09: a failed test request says nothing was changed', async () => {
    const user = userEvent.setup()
    server.use(
      http.post(TEST, () =>
        HttpResponse.json(
          {
            error: {
              code: 'INTERNAL',
              message: 'Something went wrong.',
              details: {},
              request_id: 'r',
            },
          },
          { status: 500 },
        ),
      ),
    )
    renderScreen()

    await user.click(
      await screen.findByRole('button', { name: 'Test connection' }),
    )

    expect(await screen.findByText('The test could not be run')).toBeVisible()
    expect(screen.getByText(/Nothing was changed/)).toBeVisible()
  })

  it('UX-09: says setup happens outside TrustTable and never offers to install or download', async () => {
    renderScreen()

    expect(
      await screen.findByText(/does not download, install, start or configure/),
    ).toBeVisible()
    const setup = screen
      .getByRole('heading', { name: 'Setting it up' })
      .closest('section') as HTMLElement
    expect(
      within(setup).getByRole('link', { name: 'Settings' }),
    ).toHaveAttribute('href', '/settings')
    expect(
      screen.queryByRole('button', { name: /install|download|start/i }),
    ).toBeNull()
  })

  it('UX-09: never requests the Advanced settings or shows an address', async () => {
    let advancedRequested = false
    server.use(
      http.get('http://localhost/api/v1/settings/advanced', () => {
        advancedRequested = true
        return HttpResponse.json({})
      }),
    )
    renderScreen()
    await screen.findByText(
      'AI assistance is off. You can turn it on in Settings.',
    )

    expect(advancedRequested).toBe(false)
    expect(document.body.textContent).not.toMatch(/https?:\/\//)
  })
})
