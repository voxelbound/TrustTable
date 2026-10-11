import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import {
  apiErrorBody,
  makeObservationsListResponse,
  makeScopedWindowResponse,
} from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { ObservationInspectorRoute } from './ObservationInspectorRoute'

const ANALYSIS_ID = 'observation-inspector-under-test'
const OBSERVATION_ID = 'structural.mixed_types.observation.amount'
const OBSERVATIONS_URL =
  'http://localhost/api/v1/analyses/:analysisId/observations'
const WINDOW_URL = `${OBSERVATIONS_URL}/:observationId/row-context`

const OBSERVATION = {
  observation_id: OBSERVATION_ID,
  kind: 'value_evidence',
  producer_detector_id: 'structural.mixed_types',
  summary:
    "Column 'amount' has 12 non-blank value(s) of more than one shape: 9 numeric-like, 3 text-like.",
  affected_columns: [
    { original_name: 'amount', internal_key: 'amount', ordinal: 1 },
  ],
  affected_row_numbers: [4, 7, 9],
  scope: 'full',
}

function serveObservations(overrides: Partial<typeof OBSERVATION> = {}): void {
  server.use(
    http.get(OBSERVATIONS_URL, () =>
      HttpResponse.json(
        makeObservationsListResponse({
          items: [{ ...OBSERVATION, ...overrides }],
        }),
      ),
    ),
  )
}

function renderInspector(search = '', id = OBSERVATION_ID) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      {
        path: '/analyses/:analysisId/observations/:observationId/inspector',
        element: <ObservationInspectorRoute />,
      },
      {
        path: '/analyses/:analysisId/overview',
        element: <p>Overview screen</p>,
      },
    ],
    {
      initialEntries: [
        `/analyses/${ANALYSIS_ID}/observations/${encodeURIComponent(id)}/inspector${search}`,
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
 * request's address. */
function recordWindow() {
  const seen: string[] = []
  server.use(
    http.get(WINDOW_URL, ({ request, params }) => {
      const url = new URL(request.url)
      seen.push(`${params.observationId as string}${url.search}`)
      const row = Number(url.searchParams.get('anchor_row'))
      return HttpResponse.json(
        makeScopedWindowResponse({
          rows: [
            {
              row_number: row,
              is_anchor: true,
              is_marked: true,
              values: [`id-${row}`, `amount-${row}`],
            },
          ],
          actual_before: 0,
          actual_after: 0,
        }),
      )
    }),
  )
  return seen
}

describe('ObservationInspectorRoute', () => {
  it('shows the observation, its example rows and the marked column, and says they are examples', async () => {
    serveObservations()
    recordWindow()

    renderInspector()

    expect(await screen.findByText('id-4')).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Inspect the example rows' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/9 numeric-like, 3 text-like/)).toBeInTheDocument()
    expect(screen.getByText('id-4').closest('tr')).toHaveAttribute(
      'aria-current',
      'true',
    )
    expect(screen.getByText(/\(this example row\)/)).toBeInTheDocument()
    // The position is of the example rows and says they are not all the rows.
    expect(screen.getByText(/Example row 1 of 3/)).toBeInTheDocument()
    expect(
      screen.getByText(/may count more rows than it lists/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('columnheader', { name: /amount/ }),
    ).toHaveTextContent('affected')
  })

  it('steps to the next example row and asks the server for that row only', async () => {
    serveObservations()
    const seen = recordWindow()
    renderInspector()
    await screen.findByText('id-4')

    const user = userEvent.setup()
    await user.click(screen.getByRole('link', { name: 'Next example row' }))

    expect(await screen.findByText('id-7')).toBeInTheDocument()
    expect(seen[0]).toBe(`${OBSERVATION_ID}?anchor_row=4&before=5&after=5`)
    expect(seen).toContain(`${OBSERVATION_ID}?anchor_row=7&before=5&after=5`)
    expect(screen.getByText(/Example row 2 of 3/)).toBeInTheDocument()
  })

  it('never wraps: the last example row has no next', async () => {
    serveObservations()
    recordWindow()
    renderInspector('?row=9')

    expect(await screen.findByText(/Example row 3 of 3/)).toBeInTheDocument()
    expect(screen.getByText(/This is the last example row/)).toBeInTheDocument()
    expect(screen.getByText('Next example row').closest('a')).toBeNull()
  })

  it('falls back to the first example row for a row that is not one, and never asks the server for it', async () => {
    serveObservations()
    const seen = recordWindow()

    renderInspector('?row=5')

    expect(await screen.findByText('id-4')).toBeInTheDocument()
    expect(seen.every((entry) => !entry.includes('anchor_row=5'))).toBe(true)

    // Not a number either.
    renderInspector('?row=1e3')
    expect(seen.every((entry) => !entry.includes('1e3'))).toBe(true)
  })

  it('says there is nothing to inspect for an observation without example rows, and loads no rows', async () => {
    serveObservations({ affected_row_numbers: [] })
    const seen = recordWindow()

    renderInspector()

    expect(
      await screen.findByText(/does not list example rows/),
    ).toBeInTheDocument()
    expect(seen).toEqual([])
  })

  it('says so for an observation that does not exist, and loads no rows', async () => {
    serveObservations()
    const seen = recordWindow()

    renderInspector('', 'no.such.observation')

    expect(
      await screen.findByText('This observation was not found.'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Back to the overview' }),
    ).toBeVisible()
    expect(seen).toEqual([])
  })

  it('carries an id that needs encoding to the server unchanged', async () => {
    const odd = 'x.observation.a b/c?d#e'
    serveObservations({ observation_id: odd })
    const seen = recordWindow()

    renderInspector('', odd)

    expect(await screen.findByText('id-4')).toBeInTheDocument()
    expect(seen[0]).toBe(`${odd}?anchor_row=4&before=5&after=5`)
  })

  it('renders hostile cell values as plain text, never as markup or a formula', async () => {
    serveObservations()
    server.use(
      http.get(WINDOW_URL, () =>
        HttpResponse.json(
          makeScopedWindowResponse({
            rows: [
              {
                row_number: 4,
                is_anchor: true,
                is_marked: true,
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

  it('keeps a very long value shortened until the reader asks for all of it', async () => {
    serveObservations()
    const long = 'x'.repeat(500)
    server.use(
      http.get(WINDOW_URL, () =>
        HttpResponse.json(
          makeScopedWindowResponse({
            rows: [
              {
                row_number: 4,
                is_anchor: true,
                is_marked: true,
                values: ['1004', long],
              },
            ],
            actual_before: 0,
            actual_after: 0,
          }),
        ),
      ),
    )
    renderInspector()

    const reveal = await screen.findByRole('button', {
      name: /Show all 500 characters of amount in row 4/,
    })
    expect(screen.queryByText(long)).not.toBeInTheDocument()

    await userEvent.setup().click(reveal)

    expect(await screen.findByText(long)).toBeInTheDocument()
  })

  it('states a busy refusal and offers to try again', async () => {
    serveObservations()
    server.use(
      http.get(WINDOW_URL, () =>
        HttpResponse.json(
          apiErrorBody(
            'INSPECTOR_BUSY',
            'The data inspector is busy right now. Try again shortly.',
          ),
          { status: 429 },
        ),
      ),
    )

    renderInspector()

    expect(
      await screen.findByText(/The data inspector is busy right now/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible()
  })
})
