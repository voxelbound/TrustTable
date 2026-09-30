import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/msw/server'
import { TechnicalRoute } from './TechnicalRoute'

const ANALYSIS_ID = 'analysis-under-test'
const BASE = `http://localhost/api/v1/analyses/${ANALYSIS_ID}`

const column = (key: string, name: string, metrics = {}) => ({
  column: { internal_key: key, ordinal: 0, original_name: name },
  distinct_count: 7,
  inferred_type: 'integer',
  metrics,
  null_count: 2,
  warnings: [],
})

function makeResource() {
  return {
    analysis_id: ANALYSIS_ID,
    cancelled_at: null,
    completed_at: '2026-09-30T10:00:05Z',
    created_at: '2026-09-30T10:00:00Z',
    dataset: {
      byte_size: 2048,
      content_hash: 'c'.repeat(64),
      created_at: '2026-09-30T10:00:00Z',
      dataset_id: 'dataset-1',
      format: 'csv',
      original_filename: 'sales.csv',
      source_type: 'upload',
    },
    failed_at: null,
    failure: null,
    finding_count: 3,
    security_exposure: {
      model_provider_enabled: false,
      sample_transmission_enabled: false,
    },
    started_at: '2026-09-30T10:00:01Z',
    state: 'completed',
    trust_assessment: null,
  }
}

function makeProfile(overrides: Record<string, unknown> = {}) {
  return {
    column_profiles: [
      column('c0', 'amount', { min: 1, max: 99 }),
      column('c1', '<img src=x onerror=alert(1)>'),
    ],
    dataset_metrics: { row_count: 100 },
    sampling: {
      method: null,
      population_size: 100,
      sample_size: 100,
      scope: 'all_rows',
    },
    schema_version: 'profile-v1',
    timing: {
      completed_at: '2026-09-30T10:00:04Z',
      duration_ms: 1234,
      started_at: '2026-09-30T10:00:03Z',
    },
    warnings: [{ code: 'profiling.example', message: 'Example warning' }],
    ...overrides,
  }
}

const finding = (id: string, detector: string, version: string, c: number) => ({
  affected_columns: [],
  affected_row_count: 1,
  calculated_observation: 'obs',
  category: 'completeness',
  confidence: c,
  detector_id: detector,
  detector_version: version,
  dismissal_reason: null,
  evidence_count: 1,
  finding_id: id,
  note: null,
  priority_score: 10,
  review_state: 'unreviewed',
  reviewed_at: null,
  severity: 'medium',
})

function useApi({
  profile = makeProfile(),
  findings = [
    finding('0', 'completeness.nulls', '1.0.0', 0.9),
    finding('1', 'completeness.nulls', '1.0.0', 0.7),
    finding('2', 'validity.range', '2.1.0', 0.8),
  ],
  total = findings.length,
}: {
  profile?: ReturnType<typeof makeProfile>
  findings?: ReturnType<typeof finding>[]
  total?: number
} = {}) {
  server.use(
    http.get(BASE, () => HttpResponse.json(makeResource())),
    http.get(`${BASE}/profile`, () => HttpResponse.json(profile)),
    http.get(`${BASE}/findings`, () =>
      HttpResponse.json({ items: findings, total_items: total }),
    ),
  )
}

function renderTechnical() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [{ path: '/analyses/:analysisId/technical', element: <TechnicalRoute /> }],
    { initialEntries: [`/analyses/${ANALYSIS_ID}/technical`] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('TechnicalRoute', () => {
  it('labels a full-data profile and shows dataset, timing and metrics', async () => {
    useApi()
    renderTechnical()

    expect(
      await screen.findByText(/Full data: all 100 rows were profiled/),
    ).toBeInTheDocument()
    expect(screen.getByText('sales.csv')).toBeInTheDocument()
    expect(screen.getByText('profile-v1')).toBeInTheDocument()
    expect(screen.getByText('1234')).toBeInTheDocument()
    expect(screen.getByText('row_count')).toBeInTheDocument()
    expect(screen.getByText('profiling.example: Example warning')).toBeVisible()
    expect(
      screen.getByText(/Dataset samples sent to a model: no/),
    ).toBeVisible()
  })

  it('labels a sampled profile with its sample and population sizes', async () => {
    useApi({
      profile: makeProfile({
        sampling: {
          method: 'random',
          population_size: 5000,
          sample_size: 500,
          scope: 'sample',
        },
      }),
    })
    renderTechnical()

    expect(
      await screen.findByText(
        /Sampled: 500 of 5000 rows were profiled \(scope: sample, method: random\)/,
      ),
    ).toBeInTheDocument()
  })

  it('keeps column metrics collapsed until expanded', async () => {
    useApi()
    renderTechnical()
    const user = userEvent.setup()

    const toggle = await screen.findByRole('button', {
      name: 'Show metrics for amount',
    })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('max')).not.toBeInTheDocument()

    await user.click(toggle)

    expect(
      screen.getByRole('button', { name: 'Hide metrics for amount' }),
    ).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('max')).toBeInTheDocument()
    expect(screen.getByText('99')).toBeInTheDocument()
  })

  it('summarizes detectors with version, count and confidence range', async () => {
    useApi()
    renderTechnical()

    const table = await screen.findByRole('table', {
      name: 'Detectors and versions',
    })
    const nulls = within(table).getByRole('row', {
      name: /completeness\.nulls/,
    })
    expect(within(nulls).getByText('1.0.0')).toBeInTheDocument()
    expect(within(nulls).getByText('2')).toBeInTheDocument()
    expect(within(nulls).getByText('0.7–0.9')).toBeInTheDocument()
    const range = within(table).getByRole('row', { name: /validity\.range/ })
    expect(within(range).getByText('0.8')).toBeInTheDocument()
  })

  it('states honestly what the API does not expose', async () => {
    useApi()
    renderTechnical()

    expect(
      await screen.findByText(
        /thresholds and analysis-level prompt and model metadata are not available/i,
      ),
    ).toBeInTheDocument()
  })

  it('discloses when the detector summary covers only part of the findings', async () => {
    useApi({
      findings: [finding('0', 'completeness.nulls', '1.0.0', 0.9)],
      total: 40,
    })
    renderTechnical()

    expect(
      await screen.findByText('Based on the first 1 of 40 findings.'),
    ).toBeInTheDocument()
  })

  it('shows an empty detector state when nothing was found', async () => {
    useApi({ findings: [] })
    renderTechnical()

    expect(
      await screen.findByText(/No detector produced a finding/),
    ).toBeInTheDocument()
  })

  it('renders dataset-derived column names as inert text', async () => {
    useApi()
    renderTechnical()

    const hostile = '<img src=x onerror=alert(1)>'
    expect(await screen.findByText(hostile)).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
  })

  it('shows an accessible error for the profile without hiding other sections', async () => {
    useApi()
    server.use(
      http.get(`${BASE}/profile`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'NOT_FOUND',
              message: 'Profile is not available.',
              details: {},
              request_id: 'req-1',
            },
          },
          { status: 404 },
        ),
      ),
    )
    renderTechnical()

    expect(
      await screen.findByText('Could not load the profile'),
    ).toBeInTheDocument()
    expect(await screen.findByText('sales.csv')).toBeInTheDocument()
    expect(screen.queryByText(/were profiled/)).not.toBeInTheDocument()
  })
})
