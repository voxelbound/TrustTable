import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { makeObservationsListResponse } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { ObservationsList } from './ObservationsList'

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <ObservationsList analysisId="obs-under-test" />
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

const OBSERVATION = {
  observation_id: 'structural.mixed_types.observation.amount',
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

describe('ObservationsList', () => {
  it('shows an empty state when nothing was observed', async () => {
    renderList()

    expect(
      await screen.findByText('No observations were recorded.'),
    ).toBeVisible()
  })

  it('lists each observation as plain, neutral text with its example rows', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/observations',
        () =>
          HttpResponse.json(
            makeObservationsListResponse({ items: [OBSERVATION] }),
          ),
      ),
    )
    renderList()

    const section = (
      await screen.findByRole('heading', {
        name: 'Worth knowing',
      })
    ).closest('section') as HTMLElement
    const items = await within(section).findAllByRole('listitem')
    expect(items).toHaveLength(1)
    expect(items[0].textContent).toContain('9 numeric-like, 3 text-like')
    expect(items[0].textContent).toContain('Example rows: 4, 7, 9')
  })

  it('is neutral: no severity badge, no review control, no dismiss action', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/observations',
        () =>
          HttpResponse.json(
            makeObservationsListResponse({ items: [OBSERVATION] }),
          ),
      ),
    )
    renderList()

    const section = (
      await screen.findByRole('heading', {
        name: 'Worth knowing',
      })
    ).closest('section') as HTMLElement
    await within(section).findAllByRole('listitem')
    expect(within(section).queryByRole('button')).not.toBeInTheDocument()
    // The only link is the way into the example rows (`UX-06` part b): a
    // navigation, never a review, dismiss or severity control.
    const links = within(section).getAllByRole('link')
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveTextContent('Inspect the example rows')
    expect(section.textContent?.toLowerCase()).not.toMatch(
      /severity|critical|high|medium|low|dismiss|confidence|priority/,
    )
    expect(section.textContent).toContain(
      'They do not affect the trust assessment',
    )
  })

  it('UX-06b: links an observation that has example rows to its inspector, and one without rows to nothing', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/observations',
        () =>
          HttpResponse.json(
            makeObservationsListResponse({
              items: [
                OBSERVATION,
                {
                  ...OBSERVATION,
                  observation_id:
                    'completeness.concentrated_missingness.observation.a b/c',
                  summary: 'An observation that lists no example rows.',
                  affected_row_numbers: [],
                },
              ],
            }),
          ),
      ),
    )
    renderList()

    const links = await screen.findAllByRole('link', {
      name: /Inspect the example rows/,
    })
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute(
      'href',
      '/analyses/obs-under-test/observations/structural.mixed_types.observation.amount/inspector',
    )
  })

  it('UX-06b: encodes an observation id so it cannot change the address', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/observations',
        () =>
          HttpResponse.json(
            makeObservationsListResponse({
              items: [
                {
                  ...OBSERVATION,
                  observation_id: 'x.observation.a b/c?d#e',
                },
              ],
            }),
          ),
      ),
    )
    renderList()

    const link = await screen.findByRole('link', {
      name: /Inspect the example rows/,
    })
    expect(link).toHaveAttribute(
      'href',
      '/analyses/obs-under-test/observations/x.observation.a%20b%2Fc%3Fd%23e/inspector',
    )
  })

  it('fails soft when the observations cannot be loaded', async () => {
    server.use(
      http.get(
        'http://localhost/api/v1/analyses/:analysisId/observations',
        () => HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )
    renderList()

    expect(
      await screen.findByText('Observations could not be loaded.'),
    ).toBeVisible()
  })
})
