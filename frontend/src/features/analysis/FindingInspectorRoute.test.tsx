import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  apiErrorBody,
  makeFindingDetailResponse,
  makeRowContextResponse,
  makeScopedWindowResponse,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { FindingInspectorRoute } from './FindingInspectorRoute'

const ANALYSIS_ID = 'inspector-under-test'
const FINDING_ID = '0'
const DETAIL_URL =
  'http://localhost/api/v1/analyses/:analysisId/findings/:findingId'
const ROW_CONTEXT_URL = `${DETAIL_URL}/row-context`
const COLUMN_CONTEXT_URL = `${DETAIL_URL}/column-context`

function renderInspector(search = '') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      {
        path: '/analyses/:analysisId/findings/:findingId/inspector',
        element: <FindingInspectorRoute />,
      },
      {
        path: '/analyses/:analysisId/findings/:findingId',
        element: <p>Finding screen</p>,
      },
    ],
    {
      initialEntries: [
        `/analyses/${ANALYSIS_ID}/findings/${FINDING_ID}/inspector${search}`,
      ],
    },
  )
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, ...view }
}

/** Serve one row per request, centred on the asked-for row, and record each
 * request's query parameters. */
function recordRowContext(
  overrides: Parameters<typeof makeRowContextResponse>[0] = {},
) {
  const seen: Array<{ anchor: string; before: string; after: string }> = []
  server.use(
    http.get(ROW_CONTEXT_URL, ({ request }) => {
      const url = new URL(request.url)
      const anchor = url.searchParams.get('anchor_row') ?? ''
      seen.push({
        anchor,
        before: url.searchParams.get('before') ?? '',
        after: url.searchParams.get('after') ?? '',
      })
      return HttpResponse.json(
        makeRowContextResponse({
          rows: [
            {
              row_number: Number(anchor),
              is_anchor: true,
              is_affected_by_finding: true,
              values: [`id-${anchor}`, `date-${anchor}`],
            },
          ],
          actual_before: 0,
          actual_after: 0,
          truncated_at_start: false,
          truncated_at_end: false,
          ...overrides,
        }),
      )
    }),
  )
  return seen
}

describe('FindingInspectorRoute', () => {
  it('shows the grid with the anchor row and affected column marked', async () => {
    renderInspector()

    expect(
      await screen.findByRole('columnheader', { name: 'order_id' }),
    ).toBeInTheDocument()
    const dateHeader = screen.getByRole('columnheader', {
      name: /order_date/,
    })
    expect(within(dateHeader).getByText('affected')).toBeInTheDocument()
    expect(
      screen.getByRole('columnheader', { name: 'order_id' }),
    ).not.toHaveTextContent('affected')

    const anchorCell = await screen.findByText('2099-01-01')
    const anchorRow = anchorCell.closest('tr')
    expect(anchorRow).toHaveAttribute('aria-current', 'true')
    // The affected value is announced as affected, not only coloured.
    expect(anchorCell.closest('td')).toHaveTextContent('(affected value)')
    // The unaffected column of the same row is not.
    expect(screen.getByText('1004').closest('td')).not.toHaveTextContent(
      '(affected value)',
    )
    expect(
      screen.getByText('order_date has 2 future dates.'),
    ).toBeInTheDocument()
  })

  it('states the position among the affected rows and never wraps', async () => {
    renderInspector()

    expect(await screen.findByText(/Affected row 1 of 2/)).toBeInTheDocument()
    expect(
      screen.getByText(/This is the first affected row/),
    ).toBeInTheDocument()
    expect(screen.getByText('Previous affected row').closest('a')).toBeNull()
    expect(
      screen.getByRole('link', { name: 'Next affected row' }),
    ).toHaveAttribute('href', expect.stringMatching(/\/inspector\?row=17$/))
  })

  it('steps to the next affected row and asks the server for that row only', async () => {
    const seen = recordRowContext()
    const user = userEvent.setup()
    renderInspector()

    expect(await screen.findByText('id-4')).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: 'Next affected row' }))

    expect(await screen.findByText('id-17')).toBeInTheDocument()
    expect(await screen.findByText(/Affected row 2 of 2/)).toBeInTheDocument()
    expect(
      screen.getByText(/last affected row; there is no wrap-around/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Previous affected row' }),
    ).toBeInTheDocument()
    expect(seen.map((request) => request.anchor)).toEqual(['4', '17'])
  })

  it('never asks the server for a row the finding does not name', async () => {
    const seen = recordRowContext()

    renderInspector('?row=5')

    expect(await screen.findByText('id-4')).toBeInTheDocument()
    expect(seen.map((request) => request.anchor)).toEqual(['4'])
  })

  it('ignores a row parameter that is not a plain number', async () => {
    const seen = recordRowContext()

    renderInspector('?row=1e3')

    expect(await screen.findByText('id-4')).toBeInTheDocument()
    expect(seen.map((request) => request.anchor)).toEqual(['4'])
  })

  it('carries the findings filters to the next row and back to the finding', async () => {
    recordRowContext()
    renderInspector('?severity=high&row=4')

    const next = await screen.findByRole('link', { name: 'Next affected row' })
    expect(next).toHaveAttribute(
      'href',
      expect.stringMatching(/\/inspector\?severity=high&row=17$/),
    )
    expect(
      screen.getByRole('link', { name: 'Back to the finding' }),
    ).toHaveAttribute(
      'href',
      `/analyses/${ANALYSIS_ID}/findings/${FINDING_ID}?severity=high`,
    )
  })

  it('returns to the finding', async () => {
    const user = userEvent.setup()
    renderInspector()

    await user.click(
      await screen.findByRole('link', { name: 'Back to the finding' }),
    )

    expect(await screen.findByText('Finding screen')).toBeInTheDocument()
  })

  it('does not imply every affected row can be visited when only some are listed', async () => {
    server.use(
      http.get(DETAIL_URL, () =>
        HttpResponse.json(
          makeFindingDetailResponse({
            affected_row_count: 5000,
            affected_row_numbers: [4, 17],
          }),
        ),
      ),
    )

    renderInspector()

    expect(
      await screen.findByText(
        /Only 2 of the 5000 affected rows can be visited here/,
      ),
    ).toBeInTheDocument()
  })

  function columnWideFinding() {
    server.use(
      http.get(DETAIL_URL, () =>
        HttpResponse.json(
          makeFindingDetailResponse({
            affected_row_count: 0,
            affected_row_numbers: [],
          }),
        ),
      ),
    )
  }

  it('UX-06b: a column-wide finding shows the start of the file as such, marks no row and never reads the finding row-context', async () => {
    const seen = recordRowContext()
    const columnRequests: string[] = []
    columnWideFinding()
    server.use(
      http.get(COLUMN_CONTEXT_URL, ({ request }) => {
        columnRequests.push(new URL(request.url).search)
        return HttpResponse.json(
          makeScopedWindowResponse({
            scope_kind: 'column_wide_finding',
            anchor_source: 'start_of_file',
            anchor_rows: [0],
            rows: [
              {
                row_number: 0,
                is_anchor: true,
                is_marked: false,
                values: ['1000', '2026-01-01'],
              },
              {
                row_number: 1,
                is_anchor: false,
                is_marked: false,
                values: ['1001', '2026-01-02'],
              },
            ],
            actual_before: 0,
            actual_after: 1,
            truncated_at_start: false,
            truncated_at_end: true,
          }),
        )
      }),
    )

    const { container } = renderInspector()

    expect(
      await screen.findByText(/Below is the start of the file/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/It is not evidence of the finding/),
    ).toBeInTheDocument()
    expect(screen.getByText('1000')).toBeInTheDocument()
    // Nothing is marked as affected or as an example, and nothing is "current".
    expect(container.querySelector('[aria-current]')).toBeNull()
    expect(screen.queryByText(/\(affected\)/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\(example\)/)).not.toBeInTheDocument()
    expect(screen.queryByText(/affected value/)).not.toBeInTheDocument()
    expect(screen.getByText(/first row of the file/)).toBeInTheDocument()
    // No row navigation is offered, and the centre is described as the first row.
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
    expect(screen.getByText(/either side of the first row/)).toBeInTheDocument()
    // The client chose no row: the server decides where the window is centred.
    expect(columnRequests).toEqual(['?before=5&after=5'])
    expect(seen).toEqual([])
  })

  it('UX-06b: a column-wide finding with example rows from observations says they are examples and steps among only those', async () => {
    columnWideFinding()
    const requests: string[] = []
    server.use(
      http.get(COLUMN_CONTEXT_URL, ({ request }) => {
        const url = new URL(request.url)
        requests.push(url.search)
        const row = Number(url.searchParams.get('anchor_row') ?? 7)
        return HttpResponse.json(
          makeScopedWindowResponse({
            scope_kind: 'column_wide_finding',
            anchor_source: 'observation_example',
            anchor_rows: [7, 9],
            rows: [
              {
                row_number: row,
                is_anchor: true,
                is_marked: true,
                values: [`id-${row}`, `date-${row}`],
              },
            ],
            actual_before: 0,
            actual_after: 0,
          }),
        )
      }),
    )

    renderInspector()

    expect(
      await screen.findByText(/Below are example rows from observations/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/they are not rows this finding names/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Example row 1 of 2/)).toBeInTheDocument()
    expect(
      screen.getByText(/the observations may count more rows/),
    ).toBeInTheDocument()
    expect(screen.getByText('id-7').closest('tr')).toHaveAttribute(
      'aria-current',
      'true',
    )
    expect(screen.getByText(/\(this example row\)/)).toBeInTheDocument()
    expect(screen.queryByText(/\(this affected row\)/)).not.toBeInTheDocument()

    const user = userEvent.setup()
    await user.click(screen.getByRole('link', { name: 'Next example row' }))

    expect(await screen.findByText('id-9')).toBeInTheDocument()
    expect(requests).toContain('?anchor_row=9&before=5&after=5')
  })

  it('UX-06b: a refusal of a row the server did not offer is stated, with a way back to the first window', async () => {
    columnWideFinding()
    server.use(
      http.get(COLUMN_CONTEXT_URL, () =>
        HttpResponse.json(
          apiErrorBody(
            'ROW_NOT_IN_SCOPE',
            "The requested row is not one this finding's window can be centred on.",
          ),
          { status: 404 },
        ),
      ),
    )

    renderInspector('?row=12')

    expect(
      await screen.findByText(
        /not one this finding's window can be centred on/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Back to the first window' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('UX-06b: renders hostile cell values of a column-wide window as plain text', async () => {
    columnWideFinding()
    server.use(
      http.get(COLUMN_CONTEXT_URL, () =>
        HttpResponse.json(
          makeScopedWindowResponse({
            scope_kind: 'column_wide_finding',
            anchor_source: 'start_of_file',
            anchor_rows: [0],
            rows: [
              {
                row_number: 0,
                is_anchor: true,
                is_marked: false,
                values: [
                  '<img src=x onerror="alert(1)"><script>alert(2)</script>',
                  '=HYPERLINK("http://example.invalid","click")',
                ],
              },
            ],
            actual_before: 0,
            actual_after: 0,
          }),
        ),
      ),
    )

    const { container } = renderInspector()

    expect(
      await screen.findByText(/<img src=x onerror="alert\(1\)">/),
    ).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('a[href*="example.invalid"]')).toBeNull()
  })

  it('renders hostile cell values as plain text, never as markup or a formula', async () => {
    server.use(
      http.get(ROW_CONTEXT_URL, () =>
        HttpResponse.json(
          makeRowContextResponse({
            rows: [
              {
                row_number: 4,
                is_anchor: true,
                is_affected_by_finding: true,
                values: [
                  '<img src=x onerror="alert(1)"><script>alert(2)</script>',
                  '=HYPERLINK("http://example.invalid","click")',
                ],
              },
            ],
            actual_before: 0,
            actual_after: 0,
          }),
        ),
      ),
    )

    const { container } = renderInspector()

    expect(
      await screen.findByText(
        '<img src=x onerror="alert(1)"><script>alert(2)</script>',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText('=HYPERLINK("http://example.invalid","click")'),
    ).toBeInTheDocument()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a[href^="http"]')).toBeNull()
  })

  it('keeps a long value shortened until the reader asks to see all of it', async () => {
    const long = `start-${'z'.repeat(400)}-end`
    server.use(
      http.get(ROW_CONTEXT_URL, () =>
        HttpResponse.json(
          makeRowContextResponse({
            rows: [
              {
                row_number: 4,
                is_anchor: true,
                is_affected_by_finding: true,
                values: ['1004', long],
              },
            ],
            actual_before: 0,
            actual_after: 0,
          }),
        ),
      ),
    )
    const user = userEvent.setup()
    renderInspector()

    const reveal = await screen.findByRole('button', {
      name: 'Show all 410 characters of order_date in row 4',
    })
    expect(screen.queryByText(long)).toBeNull()
    expect(screen.queryByText(/-end/)).toBeNull()

    await user.click(reveal)

    expect(await screen.findByText(long)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Show all 410/ })).toBeNull()
  })

  it('offers more rows only while more can exist, and asks for a wider window', async () => {
    const seen = recordRowContext()
    const user = userEvent.setup()
    renderInspector()

    await user.click(
      await screen.findByRole('button', { name: 'Show more rows' }),
    )

    await waitFor(() =>
      expect(seen.at(-1)).toMatchObject({ before: '15', after: '15' }),
    )
  })

  it('does not offer more rows when the file edge or the size bound ended the window', async () => {
    recordRowContext({ truncated_at_start: true, truncated_at_end: true })
    const { unmount } = renderInspector()

    expect(
      await screen.findByText(
        'Both the start and the end of the file are shown.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show more rows' })).toBeNull()
    unmount()

    recordRowContext({
      truncated_at_start: true,
      truncated_at_end: true,
      size_limited: true,
    })
    renderInspector()

    expect(await screen.findByText(/The rows are wide/)).toBeInTheDocument()
    expect(screen.queryByText(/start and the end of the file/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Show more rows' })).toBeNull()
  })

  it('explains a busy refusal and can ask again', async () => {
    let requests = 0
    server.use(
      http.get(ROW_CONTEXT_URL, () => {
        requests += 1
        if (requests === 1) {
          return HttpResponse.json(
            apiErrorBody(
              'INSPECTOR_BUSY',
              'The data inspector is busy right now. Try again shortly.',
            ),
            { status: 429 },
          )
        }
        return HttpResponse.json(makeRowContextResponse())
      }),
    )
    const user = userEvent.setup()
    renderInspector()

    expect(
      await screen.findByText(/The data inspector is busy right now/),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('2099-01-01')).toBeInTheDocument()
    expect(requests).toBe(2)
  })

  it('reports a finding that cannot be loaded and offers the way back', async () => {
    server.use(
      http.get(DETAIL_URL, () =>
        HttpResponse.json(
          apiErrorBody('FINDING_NOT_FOUND', 'No such finding.'),
          { status: 404 },
        ),
      ),
    )

    renderInspector()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No such finding.',
    )
    expect(
      screen.getByRole('link', { name: 'Back to the finding' }),
    ).toBeInTheDocument()
  })
})
