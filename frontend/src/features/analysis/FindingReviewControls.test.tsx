import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  apiErrorBody,
  makeFindingDetailResponse,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { FindingDetailRoute } from './FindingDetailRoute'

const ANALYSIS_ID = 'review-controls-under-test'
const BASE = 'http://localhost/api/v1'

interface Review {
  state: string
  note: string | null
  dismissal_reason: string | null
}

/** A stateful stand-in for the server: PUT stores the review, GET detail
 * returns whatever was stored — so a passing test proves the screen shows
 * the persisted state after a real round trip, not local form state. */
function installReviewServer(initial?: Review) {
  let stored: Review | null = initial ?? null
  const puts: Review[] = []
  server.use(
    http.get(`${BASE}/analyses/:analysisId/findings/:findingId`, () =>
      HttpResponse.json(
        makeFindingDetailResponse(
          stored
            ? {
                review_state: stored.state,
                note: stored.note,
                dismissal_reason: stored.dismissal_reason,
                reviewed_at: '2026-09-29T10:00:00Z',
              }
            : {},
        ),
      ),
    ),
    http.put(
      `${BASE}/analyses/:analysisId/findings/:findingId/review`,
      async ({ request }) => {
        const body = (await request.json()) as Review
        puts.push(body)
        stored = body
        return HttpResponse.json({
          finding_id: '0',
          review_state: body.state,
          note: body.note,
          dismissal_reason: body.dismissal_reason,
          reviewed_at: '2026-09-29T10:00:00Z',
        })
      },
    ),
  )
  return { puts }
}

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
    ],
    { initialEntries: [`/analyses/${ANALYSIS_ID}/findings/0`] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('FindingReviewControls', () => {
  it('saves a confirmed review with the exact body and shows the persisted state', async () => {
    const { puts } = installReviewServer()
    const user = userEvent.setup()
    renderDetail()

    await screen.findByRole('button', { name: 'Save review' })
    expect(
      screen.getByText('Unreviewed', { selector: 'strong' }),
    ).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Review state'), 'confirmed')
    await user.type(screen.getByLabelText('Note (optional)'), '  checked  ')
    await user.click(screen.getByRole('button', { name: 'Save review' }))

    expect(await screen.findByText('Review saved.')).toBeInTheDocument()
    expect(puts).toEqual([
      { state: 'confirmed', note: 'checked', dismissal_reason: null },
    ])
    // The "Current review" line comes from the refetched detail response.
    expect(
      await screen.findByText('Confirmed', { selector: 'strong' }),
    ).toBeInTheDocument()
  })

  it('blocks a dismissal without a reason and submits it once a reason is given', async () => {
    const { puts } = installReviewServer()
    const user = userEvent.setup()
    renderDetail()

    await screen.findByRole('button', { name: 'Save review' })
    await user.selectOptions(screen.getByLabelText('Review state'), 'dismissed')

    expect(
      screen.getByText('Enter a reason to dismiss this finding.'),
    ).toBeInTheDocument()
    const save = screen.getByRole('button', { name: 'Save review' })
    expect(save).toBeDisabled()
    await user.click(save)
    expect(puts).toHaveLength(0)

    await user.type(
      screen.getByLabelText('Dismissal reason (required)'),
      'Known test rows',
    )
    expect(save).toBeEnabled()
    await user.click(save)

    expect(await screen.findByText('Review saved.')).toBeInTheDocument()
    expect(puts).toEqual([
      {
        state: 'dismissed',
        note: null,
        dismissal_reason: 'Known test rows',
      },
    ])
  })

  it('does not send a stale dismissal reason after switching away from dismissed', async () => {
    const { puts } = installReviewServer()
    const user = userEvent.setup()
    renderDetail()

    await screen.findByRole('button', { name: 'Save review' })
    const stateSelect = screen.getByLabelText('Review state')
    await user.selectOptions(stateSelect, 'dismissed')
    await user.type(
      screen.getByLabelText('Dismissal reason (required)'),
      'Temporary',
    )
    await user.selectOptions(stateSelect, 'needs_investigation')
    expect(screen.queryByLabelText('Dismissal reason (required)')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Save review' }))

    await screen.findByText('Review saved.')
    expect(puts).toEqual([
      { state: 'needs_investigation', note: null, dismissal_reason: null },
    ])
  })

  it('prefills the form from a previously saved review', async () => {
    installReviewServer({
      state: 'dismissed',
      note: 'seen before',
      dismissal_reason: 'Duplicate of another finding',
    })
    renderDetail()

    expect(
      await screen.findByLabelText('Dismissal reason (required)'),
    ).toHaveValue('Duplicate of another finding')
    expect(screen.getByLabelText('Review state')).toHaveValue('dismissed')
    expect(screen.getByLabelText('Note (optional)')).toHaveValue('seen before')
    expect(
      screen.getByText('Dismissed', { selector: 'strong' }),
    ).toBeInTheDocument()
  })

  it('shows a server rejection as an accessible inline error and no success message', async () => {
    server.use(
      http.put(`${BASE}/analyses/:analysisId/findings/:findingId/review`, () =>
        HttpResponse.json(
          apiErrorBody('REVIEW_INVALID', 'The review could not be saved.'),
          { status: 422 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderDetail()

    await screen.findByRole('button', { name: 'Save review' })
    await user.selectOptions(screen.getByLabelText('Review state'), 'confirmed')
    await user.click(screen.getByRole('button', { name: 'Save review' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not save the review')
    expect(alert).toHaveTextContent('The review could not be saved.')
    expect(screen.queryByText('Review saved.')).toBeNull()
  })
})
