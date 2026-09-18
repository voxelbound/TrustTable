import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  apiErrorBody,
  makeAnswerGuidedQuestionResponse,
  makeContextResponse,
  makeQuestionListResponse,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { ContextRoute } from './ContextRoute'

const ANALYSIS_ID = 'context-under-test'

function renderContext() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [{ path: '/analyses/:analysisId/context', element: <ContextRoute /> }],
    { initialEntries: [`/analyses/${ANALYSIS_ID}/context`] },
  )

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )

  return router
}

describe('ContextRoute', () => {
  it('renders the five editable fields with their value and provenance', async () => {
    renderContext()

    expect(
      await screen.findByRole('heading', { name: 'Context' }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Domain', { selector: 'input' })).toHaveValue(
      'Sales / order transactions',
    )
    expect(screen.getAllByText('Calculated').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Deterministic fallback').length).toBe(2)
  })

  it('renders read-only role fields with their list values', async () => {
    renderContext()

    await screen.findByRole('heading', { name: 'Detected roles' })
    expect(screen.getByText(/order_id/)).toBeInTheDocument()
    expect(screen.getByText(/category, region/)).toBeInTheDocument()
  })

  it('saving an edited field calls PUT .../context with the current version', async () => {
    const user = userEvent.setup()
    let capturedBody: unknown = null
    server.use(
      http.put(
        'http://localhost/api/v1/analyses/:analysisId/context',
        async ({ request }) => {
          capturedBody = await request.json()
          return HttpResponse.json(makeContextResponse({ context_version: 2 }))
        },
      ),
    )

    renderContext()

    const input = await screen.findByLabelText('Row grain', {
      selector: 'input',
    })
    await user.clear(input)
    await user.type(input, 'One row per line item')
    const saveButtons = screen.getAllByRole('button', { name: 'Save' })
    await user.click(saveButtons[1])

    expect(capturedBody).toEqual({
      edits: { row_grain: 'One row per line item' },
      expected_version: 1,
    })
  })

  it('renders guided questions and submits a suggested answer', async () => {
    const user = userEvent.setup()
    let questionCallCount = 0
    server.use(
      http.post(
        'http://localhost/api/v1/analyses/:analysisId/questions/:questionId/answer',
        () => HttpResponse.json(makeAnswerGuidedQuestionResponse()),
      ),
      http.get('http://localhost/api/v1/analyses/:analysisId/questions', () => {
        questionCallCount += 1
        const base = makeQuestionListResponse().items[0]
        return HttpResponse.json(
          makeQuestionListResponse({
            items: [
              {
                ...base,
                answered_state:
                  questionCallCount > 1 ? 'answered' : 'unanswered',
              },
            ],
          }),
        )
      }),
    )

    renderContext()

    expect(
      await screen.findByText('What currency are monetary values recorded in?'),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'USD' }))

    expect(await screen.findByText('Answered.')).toBeInTheDocument()
  })

  it('renders "No open questions" when every question is resolved', async () => {
    server.use(
      http.get('http://localhost/api/v1/analyses/:analysisId/questions', () =>
        HttpResponse.json(makeQuestionListResponse({ items: [] })),
      ),
    )

    renderContext()

    expect(await screen.findByText(/No open questions/)).toBeInTheDocument()
  })

  it('finalize shows a success alert on completion', async () => {
    const user = userEvent.setup()

    renderContext()

    const finalizeButton = await screen.findByRole('button', {
      name: 'Finalize context',
    })
    await user.click(finalizeButton)

    expect(await screen.findByText('Context finalized.')).toBeInTheDocument()
  })

  it('a version-conflict response renders an inline alert, not a crash', async () => {
    const user = userEvent.setup()
    server.use(
      http.post('http://localhost/api/v1/analyses/:analysisId/finalize', () =>
        HttpResponse.json(
          apiErrorBody(
            'CONTEXT_VERSION_CONFLICT',
            'The supplied context version is out of date.',
          ),
          { status: 409 },
        ),
      ),
    )

    renderContext()

    const finalizeButton = await screen.findByRole('button', {
      name: 'Finalize context',
    })
    await user.click(finalizeButton)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(
      'The supplied context version is out of date.',
    )
  })
})
