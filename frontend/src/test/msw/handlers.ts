import { http, HttpResponse } from 'msw'
import type {
  AnalysisResource,
  AnalysisStatusResponse,
  DemoAnalysisResponse,
  FindingsListResponse,
} from '../../api'

// Absolute, matching the test-only client origin `test/setup.ts` configures
// (`http://localhost`) plus every SDK function's own `/api/v1/...` `url` —
// avoids depending on MSW's ambient relative-URL resolution (`location`)
// under Vitest's `jsdom` environment.
const BASE = 'http://localhost/api/v1'

export const DEMO_ANALYSIS_ID = 'demo-analysis-id'

export function makeAnalysisResource(
  overrides: Partial<AnalysisResource> = {},
): AnalysisResource {
  return {
    analysis_id: DEMO_ANALYSIS_ID,
    state: 'completed',
    dataset: {
      dataset_id: 'dataset-1',
      original_filename: 'sales_demo.csv',
      format: 'csv',
      byte_size: 12345,
      content_hash: 'abc123',
      source_type: 'bundled_demo',
      created_at: '2026-08-30T00:00:00Z',
    },
    security_exposure: {
      model_provider_enabled: false,
      sample_transmission_enabled: false,
    },
    trust_assessment: {
      label: 'usable_with_caution',
      score: 62,
      finding_count: 2,
      highest_priority_score: 80,
    },
    finding_count: 2,
    failure: null,
    created_at: '2026-08-30T00:00:00Z',
    started_at: '2026-08-30T00:00:01Z',
    completed_at: '2026-08-30T00:00:02Z',
    failed_at: null,
    cancelled_at: null,
    ...overrides,
  }
}

export function makeFindingsListResponse(
  overrides: Partial<FindingsListResponse> = {},
): FindingsListResponse {
  const items = overrides.items ?? [
    {
      detector_id: 'validity.future_dates',
      detector_version: '1.0.0',
      category: 'validity',
      severity: 'high',
      confidence: 0.9,
      priority_score: 80,
      calculated_observation: 'order_date has 2 future dates.',
      affected_columns: [
        { original_name: 'order_date', internal_key: 'order_date', ordinal: 3 },
      ],
      affected_row_count: 2,
      evidence_count: 2,
    },
    {
      detector_id: 'consistency.inconsistent_capitalization',
      detector_version: '1.0.0',
      category: 'consistency',
      severity: 'low',
      confidence: 0.6,
      priority_score: 20,
      calculated_observation: 'category has inconsistent capitalization.',
      affected_columns: [
        { original_name: 'category', internal_key: 'category', ordinal: 5 },
      ],
      affected_row_count: 83,
      evidence_count: 2,
    },
  ]
  return { total_items: items.length, ...overrides, items }
}

export function makeStatusResponse(
  overrides: Partial<AnalysisStatusResponse> = {},
): AnalysisStatusResponse {
  return {
    analysis_id: DEMO_ANALYSIS_ID,
    state: 'completed',
    message: 'Analysis complete.',
    cancellable: false,
    poll_interval_ms: 1000,
    ...overrides,
  }
}

export function makeDemoAnalysisResponse(
  overrides: Partial<DemoAnalysisResponse> = {},
): DemoAnalysisResponse {
  return {
    analysis: makeAnalysisResource(),
    status_url: `${BASE}/analyses/${DEMO_ANALYSIS_ID}/status`,
    ...overrides,
  }
}

export function apiErrorBody(code: string, message: string) {
  return {
    error: { code, message, details: {}, request_id: 'req-test' },
  }
}

/** Default handlers: a demo run that is already `completed` by the time
 * every endpoint is queried — matching `API-01`'s real synchronous-
 * completion behavior (`WP-023`/`WP-024`). Individual tests override
 * specific endpoints via `server.use(...)` to exercise in-progress/
 * failed/error scenarios. */
export const handlers = [
  http.post(`${BASE}/demo/sales`, () => {
    return HttpResponse.json(makeDemoAnalysisResponse(), { status: 202 })
  }),
  http.get(`${BASE}/analyses/:analysisId`, () => {
    return HttpResponse.json(makeAnalysisResource())
  }),
  http.get(`${BASE}/analyses/:analysisId/status`, () => {
    return HttpResponse.json(makeStatusResponse())
  }),
  http.get(`${BASE}/analyses/:analysisId/findings`, () => {
    return HttpResponse.json(makeFindingsListResponse())
  }),
]
