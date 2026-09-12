import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeRowContextResponse } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { RowContext } from './RowContext'

const ANALYSIS_ID = 'row-context-under-test'
const FINDING_ID = '0'

function renderRowContext(affectedRowNumbers: number[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <RowContext
        analysisId={ANALYSIS_ID}
        findingId={FINDING_ID}
        affectedRowNumbers={affectedRowNumbers}
      />
    </QueryClientProvider>,
  )
}

describe('RowContext', () => {
  it('renders nothing for a finding with zero affected rows', () => {
    const { container } = renderRowContext([])
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the column header and row values from the response', async () => {
    renderRowContext([4])

    expect(
      await screen.findByRole('columnheader', { name: 'order_id' }),
    ).toBeInTheDocument()
    expect(await screen.findByText('1004')).toBeInTheDocument()
    expect(screen.getByText('2099-01-01')).toBeInTheDocument()
  })

  it('does not render Prev/Next controls for a single affected row', async () => {
    renderRowContext([4])

    await screen.findByRole('heading', { name: 'Row context' })
    expect(screen.queryByRole('button', { name: 'Previous' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull()
  })

  it('disables Previous at the first affected row and Next at the last', async () => {
    renderRowContext([4, 17])

    const previous = await screen.findByRole('button', { name: 'Previous' })
    const next = screen.getByRole('button', { name: 'Next' })
    expect(previous).toBeDisabled()
    expect(next).not.toBeDisabled()
  })

  it('shows "Show more rows" only when the window is truncated', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/row-context',
        () =>
          HttpResponse.json(
            makeRowContextResponse({
              truncated_at_start: false,
              truncated_at_end: false,
            }),
          ),
      ),
    )

    renderRowContext([4])

    await screen.findByRole('heading', { name: 'Row context' })
    expect(screen.queryByRole('button', { name: 'Show more rows' })).toBeNull()
  })

  it('expanding the window requests a wider before/after and stops at the client cap', async () => {
    const user = userEvent.setup()
    const seenBefore: string[] = []
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/findings/:findingId/row-context',
        ({ request }) => {
          const url = new URL(request.url)
          seenBefore.push(url.searchParams.get('before') ?? '')
          return HttpResponse.json(makeRowContextResponse())
        },
      ),
    )

    renderRowContext([4])

    // Starts at 3, steps by 5, clamped to the client-side cap of 25:
    // 3 -> 8 -> 13 -> 18 -> 23 (never exceeding 25). The button briefly
    // disappears while a request is in flight (`query.data` is `undefined`
    // between queryKey changes), so it must be re-queried before each
    // click rather than reusing a stale, possibly-detached node.
    for (const expected of ['8', '13', '18', '23']) {
      const expandButton = await screen.findByRole('button', {
        name: 'Show more rows',
      })
      await user.click(expandButton)
      await waitFor(() => expect(seenBefore.at(-1)).toBe(expected))
    }
  })
})
