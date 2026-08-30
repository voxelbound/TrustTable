/**
 * TanStack Query hooks composing the already-generated `API-01` SDK
 * functions (`frontend/src/api/`, `@hey-api/openapi-ts`). No new backend
 * call shape is introduced here — this module is purely client-side
 * composition (`docs/architecture.md` §4: "Feature modules -> Query
 * hooks ... -> Generated API client").
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import {
  getAnalysisApiV1AnalysesAnalysisIdGet,
  getAnalysisFindingsApiV1AnalysesAnalysisIdFindingsGet,
  getAnalysisStatusApiV1AnalysesAnalysisIdStatusGet,
  postDemoSalesApiV1DemoSalesPost,
  type AnalysisResource,
  type AnalysisStatusResponse,
  type DemoAnalysisResponse,
  type FindingsListResponse,
} from '../../api'
import { client } from '../../api/client.gen'
import { getApiErrorMessage } from '../../lib/apiError'

/**
 * Discovered pre-existing defect (found during `WP-025` implementation,
 * not previously exercised by any real fetch call — `WP-024`'s tests
 * are backend-only via `TestClient`, and `smoke.spec.ts` calls
 * `/api/v1/version` directly with Playwright's own request context, not
 * through this generated client): `frontend/openapi-ts.config.ts`
 * configures the generated client's default `baseUrl` as `/api/v1`, but
 * every generated SDK function's `url` already carries the full
 * `/api/v1/...` path — `backend/src/trusttable_backend/api/v1/router.py`
 * mounts `APIRouter(prefix="/api/v1")` at the application root with no
 * further prefix (confirmed by direct read), so FastAPI's OpenAPI
 * `paths` are already fully qualified. Left uncorrected, every request
 * would resolve to a doubled `/api/v1/api/v1/...` path in the real
 * running application, not only in this package's tests.
 *
 * Corrected here, at this module (the sole current consumer of the
 * generated client — no other feature calls it yet), rather than
 * editing generated output or its generation config, both of which are
 * outside this package's declared scope and would require pausing for
 * a fresh approval to add. A source-level fix
 * (`frontend/openapi-ts.config.ts`'s `baseUrl` should be `''`, not
 * `/api/v1`) is noted as a follow-up for a future package, not applied
 * here.
 */
client.setConfig({ baseUrl: '' })

/** Wraps a parsed structured-error body (`lib/apiError.ts`) as a real
 * `Error` so TanStack Query's mutation/query error channel behaves
 * normally. `body` is preserved for callers that need the raw envelope
 * (e.g. the error code), not just the display message.
 *
 * `body` is assigned in the constructor body rather than as a
 * constructor parameter property — this project's `tsconfig` enables
 * `erasableSyntaxOnly`, which rejects parameter-property shorthand. */
export class ApiCallError extends Error {
  readonly body: unknown

  constructor(body: unknown) {
    super(getApiErrorMessage(body))
    this.name = 'ApiCallError'
    this.body = body
  }
}

/** `AnalysisState` values (`analysis/service.py`) that will never
 * transition further — polling stops once one of these is observed. */
export const ANALYSIS_TERMINAL_STATES = new Set([
  'completed',
  'failed',
  'cancelled',
])

const STATUS_POLL_INTERVAL_MS = 1000

export interface QueryEnabledOption {
  enabled?: boolean
}

export function useCreateDemoAnalysis() {
  return useMutation<DemoAnalysisResponse, ApiCallError, void>({
    mutationFn: async () => {
      // Narrow on `result.data === undefined` (not `result.error`,
      // and not by destructuring `data`/`error` into separate bindings
      // up front): this route's generated SDK function types its error
      // branch as plain `unknown` (no declared error schema), so a
      // truthiness check on `error` cannot exclude the failure branch
      // and `data` remains possibly-`undefined` after the check.
      const result = await postDemoSalesApiV1DemoSalesPost()
      if (result.data === undefined) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
  })
}

export function useAnalysisStatus(analysisId: string | undefined) {
  return useQuery<AnalysisStatusResponse, ApiCallError>({
    queryKey: ['analysis-status', analysisId],
    queryFn: async () => {
      const result = await getAnalysisStatusApiV1AnalysesAnalysisIdStatusGet({
        path: { analysis_id: analysisId as string },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled: Boolean(analysisId),
    // Bounded polling: stops entirely once a terminal state is observed
    // (`docs/ui-specification.md` §4.3's "named stages" requirement),
    // matching `analysis.service`'s own fixed eight-state contract.
    refetchInterval: (query) => {
      const state = query.state.data?.state
      if (!state || ANALYSIS_TERMINAL_STATES.has(state)) {
        return false
      }
      return STATUS_POLL_INTERVAL_MS
    },
  })
}

export function useAnalysisResource(
  analysisId: string | undefined,
  options?: QueryEnabledOption,
) {
  return useQuery<AnalysisResource, ApiCallError>({
    queryKey: ['analysis-resource', analysisId],
    queryFn: async () => {
      const result = await getAnalysisApiV1AnalysesAnalysisIdGet({
        path: { analysis_id: analysisId as string },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled: Boolean(analysisId) && (options?.enabled ?? true),
  })
}

export function useAnalysisFindings(
  analysisId: string | undefined,
  options?: QueryEnabledOption,
) {
  return useQuery<FindingsListResponse, ApiCallError>({
    queryKey: ['analysis-findings', analysisId],
    queryFn: async () => {
      const result =
        await getAnalysisFindingsApiV1AnalysesAnalysisIdFindingsGet({
          path: { analysis_id: analysisId as string },
        })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled: Boolean(analysisId) && (options?.enabled ?? true),
  })
}
