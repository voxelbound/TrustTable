import { http, HttpResponse } from 'msw'
import type {
  AnalysisResource,
  AnalysisStatusResponse,
  AnswerGuidedQuestionResponse,
  ClarificationQuestionListResponse,
  ContextResponse,
  DemoAnalysisResponse,
  FindingDetailResponse,
  FindingEvidenceListResponse,
  FindingExplanationResponse,
  FindingsListResponse,
  RowContextResponse,
  UploadAnalysisResponse,
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
      finding_id: '0',
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
      finding_id: '1',
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

export function makeFindingDetailResponse(
  overrides: Partial<FindingDetailResponse> = {},
): FindingDetailResponse {
  return {
    finding_id: '0',
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
    affected_row_numbers: [4, 17],
    evidence_count: 2,
    security_exposure: {
      model_provider_enabled: false,
      sample_transmission_enabled: false,
    },
    ...overrides,
  }
}

export function makeRowContextResponse(
  overrides: Partial<RowContextResponse> = {},
): RowContextResponse {
  const columns = overrides.columns ?? [
    { original_name: 'order_id', internal_key: 'order_id', ordinal: 0 },
    { original_name: 'order_date', internal_key: 'order_date', ordinal: 3 },
  ]
  const rows = overrides.rows ?? [
    {
      row_number: 2,
      is_anchor: false,
      is_affected_by_finding: false,
      values: ['1002', '2026-01-02'],
    },
    {
      row_number: 3,
      is_anchor: false,
      is_affected_by_finding: false,
      values: ['1003', '2026-01-03'],
    },
    {
      row_number: 4,
      is_anchor: true,
      is_affected_by_finding: true,
      values: ['1004', '2099-01-01'],
    },
    {
      row_number: 5,
      is_anchor: false,
      is_affected_by_finding: false,
      values: ['1005', '2026-01-05'],
    },
    {
      row_number: 6,
      is_anchor: false,
      is_affected_by_finding: false,
      values: ['1006', '2026-01-06'],
    },
  ]
  return {
    columns,
    requested_before: 3,
    requested_after: 3,
    actual_before: 2,
    actual_after: 2,
    truncated_at_start: true,
    truncated_at_end: true,
    max_window: 25,
    rows,
    ...overrides,
  }
}

export function makeFindingEvidenceListResponse(
  overrides: Partial<FindingEvidenceListResponse> = {},
): FindingEvidenceListResponse {
  const items = overrides.items ?? [
    {
      evidence_id: 'validity.future_dates.evidence.order_date',
      evidence_type: 'row_set',
      display_safe_summary: "Column 'order_date' has 2 future date value(s).",
      affected_columns: [
        {
          original_name: 'order_date',
          internal_key: 'order_date',
          ordinal: 3,
        },
      ],
      affected_row_count: 2,
      scope: 'full',
    },
  ]
  return { total_items: items.length, ...overrides, items }
}

export function makeFindingExplanationResponse(
  overrides: Partial<FindingExplanationResponse> = {},
): FindingExplanationResponse {
  return {
    finding_id: '0',
    narrative: 'This is a medium-severity finding worth reviewing.',
    provenance: 'deterministic_fallback',
    provider_name: null,
    model_identifier: null,
    ai_call_status: 'not_configured',
    referenced_evidence_ids: ['validity.future_dates.evidence.order_date'],
    referenced_columns: [
      { original_name: 'order_date', internal_key: 'order_date', ordinal: 3 },
    ],
    ...overrides,
  }
}

function makeContextFieldValue(
  value: string | string[],
  inferenceSource = 'calculated',
) {
  return {
    value,
    confidence: 0.7,
    inference_source: inferenceSource,
    confirmation_state: 'inferred',
    evidence_ids: [],
  }
}

export function makeContextResponse(
  overrides: Partial<ContextResponse> = {},
): ContextResponse {
  return {
    context_version: 1,
    schema_version: '1',
    probable_domain: makeContextFieldValue('Sales / order transactions'),
    row_grain: makeContextFieldValue('One row per order_id'),
    primary_entity: makeContextFieldValue('order'),
    candidate_keys: makeContextFieldValue(['order_id']),
    business_dates: makeContextFieldValue(['order_date']),
    measure_roles: makeContextFieldValue(['quantity', 'unit_price']),
    dimensions: makeContextFieldValue(['category', 'region']),
    currency_behavior: makeContextFieldValue('', 'deterministic_fallback'),
    expected_business_rules: makeContextFieldValue(
      '',
      'deterministic_fallback',
    ),
    ...overrides,
  }
}

export function makeQuestionListResponse(
  overrides: Partial<ClarificationQuestionListResponse> = {},
): ClarificationQuestionListResponse {
  const items = overrides.items ?? [
    {
      question_id: 'cq-currency_behavior-1',
      context_field: 'currency_behavior',
      concise_text: 'What currency are monetary values recorded in?',
      explanation: 'Affects how monetary findings are interpreted.',
      suggested_answers: ['USD', 'EUR'],
      inferred_default: null,
      affected_assumptions: ['Monetary value interpretation'],
      free_text_allowed: true,
      answered_state: 'unanswered',
    },
  ]
  return { total_items: items.length, ...overrides, items }
}

export function makeAnswerGuidedQuestionResponse(
  overrides: Partial<AnswerGuidedQuestionResponse> = {},
): AnswerGuidedQuestionResponse {
  return {
    context: makeContextResponse({ context_version: 2 }),
    question: {
      ...makeQuestionListResponse().items[0],
      answered_state: 'answered',
    },
    answer: {
      question_id: 'cq-currency_behavior-1',
      selected_answer_or_free_text: 'USD',
      answered_timestamp: '2026-09-18T00:00:00Z',
      resulting_context_changes: ['currency_behavior'],
      provenance: 'user_confirmed',
    },
    ...overrides,
  }
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

export function makeUploadAnalysisResponse(
  overrides: Partial<UploadAnalysisResponse> = {},
): UploadAnalysisResponse {
  return {
    analysis: makeAnalysisResource({
      dataset: {
        dataset_id: 'dataset-upload-1',
        original_filename: 'my-data.csv',
        format: 'csv',
        byte_size: 456,
        content_hash: 'def456',
        source_type: 'upload',
        created_at: '2026-09-07T00:00:00Z',
      },
    }),
    status_url: `${BASE}/analyses/upload-analysis-id/status`,
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
  http.post(`${BASE}/analyses`, () => {
    return HttpResponse.json(makeUploadAnalysisResponse(), { status: 202 })
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
  http.get(`${BASE}/analyses/:analysisId/findings/:findingId`, () => {
    return HttpResponse.json(makeFindingDetailResponse())
  }),
  http.get(`${BASE}/analyses/:analysisId/findings/:findingId/evidence`, () => {
    return HttpResponse.json(makeFindingEvidenceListResponse())
  }),
  http.get(
    `${BASE}/analyses/:analysisId/findings/:findingId/explanation`,
    () => {
      return HttpResponse.json(makeFindingExplanationResponse())
    },
  ),
  http.get(`${BASE}/analyses/:analysisId/context`, () => {
    return HttpResponse.json(makeContextResponse())
  }),
  http.put(`${BASE}/analyses/:analysisId/context`, () => {
    return HttpResponse.json(makeContextResponse({ context_version: 2 }))
  }),
  http.get(`${BASE}/analyses/:analysisId/questions`, () => {
    return HttpResponse.json(makeQuestionListResponse())
  }),
  http.post(`${BASE}/analyses/:analysisId/questions/:questionId/answer`, () => {
    return HttpResponse.json(makeAnswerGuidedQuestionResponse())
  }),
  http.post(`${BASE}/analyses/:analysisId/finalize`, () => {
    return HttpResponse.json(makeAnalysisResource(), { status: 202 })
  }),
  http.get(
    `${BASE}/analyses/:analysisId/findings/:findingId/row-context`,
    () => {
      return HttpResponse.json(makeRowContextResponse())
    },
  ),
]
