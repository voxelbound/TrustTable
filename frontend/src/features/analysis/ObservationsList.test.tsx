import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { makeObservationsListResponse } from '../../test/msw/handlers'
import { server } from '../../test/msw/server'
import { ObservationsList } from './ObservationsList'

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <ObservationsList analysisId="obs-under-test" />
    </QueryClientProvider>,
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
        name: 'Data observations',
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
        name: 'Data observations',
      })
    ).closest('section') as HTMLElement
    await within(section).findAllByRole('listitem')
    expect(within(section).queryByRole('button')).not.toBeInTheDocument()
    expect(within(section).queryByRole('link')).not.toBeInTheDocument()
    expect(section.textContent?.toLowerCase()).not.toMatch(
      /severity|critical|high|medium|low|dismiss|confidence|priority/,
    )
    expect(section.textContent).toContain(
      'They do not affect the trust assessment',
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
