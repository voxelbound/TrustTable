/**
 * TanStack Query hooks composing the already-generated `API-01` SDK
 * functions (`frontend/src/api/`, `@hey-api/openapi-ts`). No new backend
 * call shape is introduced here — this module is purely client-side
 * composition (`docs/architecture.md` §4: "Feature modules -> Query
 * hooks ... -> Generated API client").
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createReportApiV1AnalysesAnalysisIdReportsPost,
  deleteAnalysisResourceApiV1AnalysesAnalysisIdDelete,
  deleteAnalysisRuleApiV1AnalysesAnalysisIdRulesRuleIdDelete,
  getAnalysisRulesApiV1AnalysesAnalysisIdRulesGet,
  getRulesExportJsonApiV1AnalysesAnalysisIdExportsRulesJsonGet,
  getRulesExportYamlApiV1AnalysesAnalysisIdExportsRulesYamlGet,
  postAnalysisRuleTestApiV1AnalysesAnalysisIdRulesRuleIdTestPost,
  downloadReportApiV1AnalysesAnalysisIdReportsReportIdDownloadGet,
  getAnalysisApiV1AnalysesAnalysisIdGet,
  getAnalysisContextApiV1AnalysesAnalysisIdContextGet,
  getAnalysisFindingApiV1AnalysesAnalysisIdFindingsFindingIdGet,
  getAnalysisFindingEvidenceApiV1AnalysesAnalysisIdFindingsFindingIdEvidenceGet,
  getAnalysisFindingExplanationApiV1AnalysesAnalysisIdFindingsFindingIdExplanationGet,
  getAnalysisFindingRowContextApiV1AnalysesAnalysisIdFindingsFindingIdRowContextGet,
  getAnalysisFindingsApiV1AnalysesAnalysisIdFindingsGet,
  getAnalysisObservationsApiV1AnalysesAnalysisIdObservationsGet,
  getAnalysisProfileApiV1AnalysesAnalysisIdProfileGet,
  getAnalysisQuestionsApiV1AnalysesAnalysisIdQuestionsGet,
  getAnalysisStatusApiV1AnalysesAnalysisIdStatusGet,
  getAnalysisSummaryApiV1AnalysesAnalysisIdSummaryGet,
  listReportsApiV1AnalysesAnalysisIdReportsGet,
  postAnalysisCancelApiV1AnalysesAnalysisIdCancelPost,
  postAnalysisFinalizeApiV1AnalysesAnalysisIdFinalizePost,
  postAnalysisQuestionAnswerApiV1AnalysesAnalysisIdQuestionsQuestionIdAnswerPost,
  postAnalysisRetryApiV1AnalysesAnalysisIdRetryPost,
  postAnalysisUploadApiV1AnalysesPost,
  postDemoSalesApiV1DemoSalesPost,
  putAnalysisContextApiV1AnalysesAnalysisIdContextPut,
  putAnalysisFindingReviewApiV1AnalysesAnalysisIdFindingsFindingIdReviewPut,
  type AnalysisProfileResponse,
  type AnalysisResource,
  type AnalysisStatusResponse,
  type AnalysisSummaryResponse,
  type AnswerGuidedQuestionResponse,
  type ClarificationQuestionListResponse,
  type ContextResponse,
  type DemoAnalysisResponse,
  type ReportListResponse,
  type ReportOptionsModel,
  type ReportResponse,
  type RetryAnalysisResponse,
  type ValidationRuleResponse,
  type ValidationRulesListResponse,
  type FindingDetailResponse,
  type FindingEvidenceListResponse,
  type FindingExplanationResponse,
  type FindingReviewRequest,
  type FindingReviewResponse,
  type FindingsListResponse,
  type ObservationsListResponse,
  type RowContextResponse,
  type UploadAnalysisResponse,
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

/** What to upload: the file and, for an Excel workbook with several
 * worksheets, the one the user picked (`ING-03`). */
export interface AnalysisUploadRequest {
  file: File
  worksheet?: string
}

/** `POST /analyses` (`API-01`/`UI-01`, extending — `WP-029`, generic
 * upload; `ING-03`, Excel with an optional `worksheet`). Mirrors
 * `useCreateDemoAnalysis`'s error-handling pattern exactly; the only
 * difference is the multipart body. `worksheet` is sent only when given,
 * so a CSV upload's request is unchanged. */
export function useCreateAnalysisUpload() {
  return useMutation<
    UploadAnalysisResponse,
    ApiCallError,
    AnalysisUploadRequest
  >({
    mutationFn: async ({ file, worksheet }: AnalysisUploadRequest) => {
      const result = await postAnalysisUploadApiV1AnalysesPost({
        body: worksheet === undefined ? { file } : { file, worksheet },
      })
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

/** `GET .../observations` (`DET-03` closure package 2, provisional): the
 * neutral, read-only data observations. Separate from findings on purpose;
 * they carry no severity, confidence or priority. */
export function useAnalysisObservations(
  analysisId: string | undefined,
  options?: QueryEnabledOption,
) {
  return useQuery<ObservationsListResponse, ApiCallError>({
    queryKey: ['analysis-observations', analysisId],
    queryFn: async () => {
      const result =
        await getAnalysisObservationsApiV1AnalysesAnalysisIdObservationsGet({
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

/** `GET .../summary` (`UX-04`, D-070): the dashboard figures a browser
 * cannot derive from the list responses (distinct affected rows, shape,
 * completeness with its sampled-or-full scope). Counts only. */
export function useAnalysisSummary(
  analysisId: string | undefined,
  options?: QueryEnabledOption,
) {
  return useQuery<AnalysisSummaryResponse, ApiCallError>({
    queryKey: ['analysis-summary', analysisId],
    queryFn: async () => {
      const result = await getAnalysisSummaryApiV1AnalysesAnalysisIdSummaryGet({
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

/** `GET .../profile` (`PROF-03` route, `UI-03` slice 5): the versioned
 * dataset and column profile, read-only, for the technical details screen. */
export function useAnalysisProfile(analysisId: string | undefined) {
  return useQuery<AnalysisProfileResponse, ApiCallError>({
    queryKey: ['analysis-profile', analysisId],
    queryFn: async () => {
      const result = await getAnalysisProfileApiV1AnalysesAnalysisIdProfileGet({
        path: { analysis_id: analysisId as string },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled: Boolean(analysisId),
  })
}

/** `GET .../findings/{finding_id}` (`API-01`, extending — `WP-027`). */
export function useFindingDetail(
  analysisId: string | undefined,
  findingId: string | undefined,
) {
  return useQuery<FindingDetailResponse, ApiCallError>({
    queryKey: ['analysis-finding-detail', analysisId, findingId],
    queryFn: async () => {
      const result =
        await getAnalysisFindingApiV1AnalysesAnalysisIdFindingsFindingIdGet({
          path: {
            analysis_id: analysisId as string,
            finding_id: findingId as string,
          },
        })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled: Boolean(analysisId) && Boolean(findingId),
  })
}

/** `PUT .../findings/{finding_id}/review` (`REV-01` route, `UI-03` slice 4).
 * Replaces the finding's review record. On success the finding's detail and
 * the findings list are refetched so the persisted state is what is shown. */
export function useSaveFindingReview(
  analysisId: string | undefined,
  findingId: string | undefined,
) {
  const queryClient = useQueryClient()
  return useMutation<FindingReviewResponse, ApiCallError, FindingReviewRequest>(
    {
      mutationFn: async (body) => {
        const result =
          await putAnalysisFindingReviewApiV1AnalysesAnalysisIdFindingsFindingIdReviewPut(
            {
              path: {
                analysis_id: analysisId as string,
                finding_id: findingId as string,
              },
              body,
            },
          )
        if (result.error) {
          throw new ApiCallError(result.error)
        }
        return result.data
      },
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: ['analysis-finding-detail', analysisId, findingId],
        })
        void queryClient.invalidateQueries({
          queryKey: ['analysis-findings', analysisId],
        })
      },
    },
  )
}

/** `GET .../findings/{finding_id}/row-context` (`FIND-01`, `WP-038`).
 * `anchorRow` selects which of the finding's own affected rows to center
 * the window on (Prev/Next jump list); `before`/`after` drive the expand
 * control. Disabled until `anchorRow` is known (only meaningful once the
 * finding detail response's `affected_row_numbers` has resolved). */
export function useFindingRowContext(
  analysisId: string | undefined,
  findingId: string | undefined,
  anchorRow: number | undefined,
  windowSize: { before: number; after: number },
) {
  return useQuery<RowContextResponse, ApiCallError>({
    queryKey: [
      'analysis-finding-row-context',
      analysisId,
      findingId,
      anchorRow,
      windowSize.before,
      windowSize.after,
    ],
    queryFn: async () => {
      const result =
        await getAnalysisFindingRowContextApiV1AnalysesAnalysisIdFindingsFindingIdRowContextGet(
          {
            path: {
              analysis_id: analysisId as string,
              finding_id: findingId as string,
            },
            query: {
              anchor_row: anchorRow as number,
              before: windowSize.before,
              after: windowSize.after,
            },
          },
        )
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled:
      Boolean(analysisId) && Boolean(findingId) && anchorRow !== undefined,
  })
}

/** `GET .../findings/{finding_id}/explanation` (`UI-02` slice 1,
 * `WP-063`). Follows the same pattern as `useFindingEvidence`. */
export function useFindingExplanation(
  analysisId: string | undefined,
  findingId: string | undefined,
) {
  return useQuery<FindingExplanationResponse, ApiCallError>({
    queryKey: ['analysis-finding-explanation', analysisId, findingId],
    queryFn: async () => {
      const result =
        await getAnalysisFindingExplanationApiV1AnalysesAnalysisIdFindingsFindingIdExplanationGet(
          {
            path: {
              analysis_id: analysisId as string,
              finding_id: findingId as string,
            },
          },
        )
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled: Boolean(analysisId) && Boolean(findingId),
  })
}

/** `GET .../findings/{finding_id}/evidence` (`API-01`, extending —
 * `WP-027`). */
export function useFindingEvidence(
  analysisId: string | undefined,
  findingId: string | undefined,
) {
  return useQuery<FindingEvidenceListResponse, ApiCallError>({
    queryKey: ['analysis-finding-evidence', analysisId, findingId],
    queryFn: async () => {
      const result =
        await getAnalysisFindingEvidenceApiV1AnalysesAnalysisIdFindingsFindingIdEvidenceGet(
          {
            path: {
              analysis_id: analysisId as string,
              finding_id: findingId as string,
            },
          },
        )
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled: Boolean(analysisId) && Boolean(findingId),
  })
}

/** `GET .../context` (`API-02`, `UI-02` slice 2, `WP-064`). */
export function useAnalysisContext(analysisId: string | undefined) {
  return useQuery<ContextResponse, ApiCallError>({
    queryKey: ['analysis-context', analysisId],
    queryFn: async () => {
      const result = await getAnalysisContextApiV1AnalysesAnalysisIdContextGet({
        path: { analysis_id: analysisId as string },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled: Boolean(analysisId),
  })
}

/** `GET .../questions` (`API-02`, `UI-02` slice 2, `WP-064`). */
export function useGuidedQuestions(analysisId: string | undefined) {
  return useQuery<ClarificationQuestionListResponse, ApiCallError>({
    queryKey: ['analysis-guided-questions', analysisId],
    queryFn: async () => {
      const result =
        await getAnalysisQuestionsApiV1AnalysesAnalysisIdQuestionsGet({
          path: { analysis_id: analysisId as string },
        })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled: Boolean(analysisId),
  })
}

export interface ConfirmContextFieldsInput {
  edits: Record<string, string>
  expectedVersion: number
}

/** `PUT .../context` (`API-02`, `UI-02` slice 2, `WP-064`). Invalidates
 * the cached context query on success so the screen reflects the new
 * version/values immediately. */
export function useConfirmContextFields(analysisId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation<ContextResponse, ApiCallError, ConfirmContextFieldsInput>({
    mutationFn: async ({ edits, expectedVersion }) => {
      const result = await putAnalysisContextApiV1AnalysesAnalysisIdContextPut({
        path: { analysis_id: analysisId as string },
        body: { edits, expected_version: expectedVersion },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['analysis-context', analysisId],
      })
    },
  })
}

export interface AnswerGuidedQuestionInput {
  questionId: string
  answerText: string
  expectedVersion: number
}

/** `POST .../questions/{question_id}/answer` (`API-02`, `UI-02` slice
 * 2, `WP-064`). Invalidates both the context and guided-questions
 * queries on success — a single answer updates both. */
export function useAnswerGuidedQuestion(analysisId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation<
    AnswerGuidedQuestionResponse,
    ApiCallError,
    AnswerGuidedQuestionInput
  >({
    mutationFn: async ({ questionId, answerText, expectedVersion }) => {
      const result =
        await postAnalysisQuestionAnswerApiV1AnalysesAnalysisIdQuestionsQuestionIdAnswerPost(
          {
            path: {
              analysis_id: analysisId as string,
              question_id: questionId,
            },
            body: {
              answer_text: answerText,
              expected_version: expectedVersion,
            },
          },
        )
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['analysis-context', analysisId],
      })
      void queryClient.invalidateQueries({
        queryKey: ['analysis-guided-questions', analysisId],
      })
    },
  })
}

/** `POST .../finalize` (`API-02`, `UI-02` slice 2, `WP-064`). */
export function useFinalizeContext(analysisId: string | undefined) {
  return useMutation<
    AnalysisResource,
    ApiCallError,
    { expectedVersion: number }
  >({
    mutationFn: async ({ expectedVersion }) => {
      const result =
        await postAnalysisFinalizeApiV1AnalysesAnalysisIdFinalizePost({
          path: { analysis_id: analysisId as string },
          body: { expected_version: expectedVersion },
        })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
  })
}

/** `POST .../cancel` (`UI-03` slice 1). Refreshes the status and resource
 * queries so the layout shows the cancelled state. */
export function useCancelAnalysis(analysisId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation<AnalysisResource, ApiCallError, void>({
    mutationFn: async () => {
      const result = await postAnalysisCancelApiV1AnalysesAnalysisIdCancelPost({
        path: { analysis_id: analysisId as string },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['analysis-status', analysisId],
      })
      void queryClient.invalidateQueries({
        queryKey: ['analysis-resource', analysisId],
      })
    },
  })
}

/** `POST .../retry` (`UI-03` slice 1). Creates a new, independent analysis
 * (`docs/api-specification.md` §6); the caller navigates to
 * `response.analysis.analysis_id`. The original analysis is not touched. */
export function useRetryAnalysis(analysisId: string | undefined) {
  return useMutation<RetryAnalysisResponse, ApiCallError, void>({
    mutationFn: async () => {
      const result = await postAnalysisRetryApiV1AnalysesAnalysisIdRetryPost({
        path: { analysis_id: analysisId as string },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
  })
}

/** `GET .../reports` (`UI-03` slice 2, `EXP-01`): the stored report
 * snapshots of an analysis, in creation order. */
export function useReports(analysisId: string | undefined) {
  return useQuery<ReportListResponse, ApiCallError>({
    queryKey: ['analysis-reports', analysisId],
    enabled: Boolean(analysisId),
    queryFn: async () => {
      const result = await listReportsApiV1AnalysesAnalysisIdReportsGet({
        path: { analysis_id: analysisId as string },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
  })
}

/** `POST .../reports` (`UI-03` slice 2): renders and stores one immutable
 * snapshot with exactly the options given (each off unless set). */
export function useCreateReport(analysisId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation<ReportResponse, ApiCallError, ReportOptionsModel>({
    mutationFn: async (options) => {
      const result = await createReportApiV1AnalysesAnalysisIdReportsPost({
        path: { analysis_id: analysisId as string },
        body: { options },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['analysis-reports', analysisId],
      })
    },
  })
}

/** `GET .../reports/{id}/download` (`UI-03` slice 2): the stored Markdown
 * of one report, exactly as served (never re-rendered). Resolves to the
 * text; the caller decides how to save it. */
export function useDownloadReport(analysisId: string | undefined) {
  return useMutation<string, ApiCallError, string>({
    mutationFn: async (reportId) => {
      const result =
        await downloadReportApiV1AnalysesAnalysisIdReportsReportIdDownloadGet({
          path: {
            analysis_id: analysisId as string,
            report_id: reportId,
          },
          parseAs: 'text',
        })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data as string
    },
  })
}

/** `GET .../rules` (`UI-03` slice 3, `RULE-01`): every stored rule with
 * its latest execution result. */
export function useRules(analysisId: string | undefined) {
  return useQuery<ValidationRulesListResponse, ApiCallError>({
    queryKey: ['analysis-rules', analysisId],
    enabled: Boolean(analysisId),
    queryFn: async () => {
      const result = await getAnalysisRulesApiV1AnalysesAnalysisIdRulesGet({
        path: { analysis_id: analysisId as string },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
  })
}

/** `POST .../rules/{rule_id}/test` (`UI-03` slice 3): re-executes one rule
 * against the immutable dataset; the refreshed rule replaces the list. */
export function useRunRule(analysisId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation<ValidationRuleResponse, ApiCallError, string>({
    mutationFn: async (ruleId) => {
      const result =
        await postAnalysisRuleTestApiV1AnalysesAnalysisIdRulesRuleIdTestPost({
          path: { analysis_id: analysisId as string, rule_id: ruleId },
        })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['analysis-rules', analysisId],
      })
    },
  })
}

/** `DELETE .../rules/{rule_id}` (`UI-03` slice 3). `204` has no body. */
export function useDeleteRule(analysisId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation<void, ApiCallError, string>({
    mutationFn: async (ruleId) => {
      const result =
        await deleteAnalysisRuleApiV1AnalysesAnalysisIdRulesRuleIdDelete({
          path: { analysis_id: analysisId as string, rule_id: ruleId },
        })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['analysis-rules', analysisId],
      })
    },
  })
}

export type RulesExportFormat = 'json' | 'yaml'

/** `GET .../exports/rules.{json,yaml}` (`UI-03` slice 3, `EXP-01`): the
 * validated-rules document exactly as served. Resolves to the text; the
 * caller decides how to save it. */
export function useDownloadRulesExport(analysisId: string | undefined) {
  return useMutation<string, ApiCallError, RulesExportFormat>({
    mutationFn: async (format) => {
      const options = {
        path: { analysis_id: analysisId as string },
        parseAs: 'text' as const,
      }
      const result =
        format === 'json'
          ? await getRulesExportJsonApiV1AnalysesAnalysisIdExportsRulesJsonGet(
              options,
            )
          : await getRulesExportYamlApiV1AnalysesAnalysisIdExportsRulesYamlGet(
              options,
            )
      if (result.error) {
        throw new ApiCallError(result.error)
      }
      return result.data as string
    },
  })
}

/** `DELETE /analyses/{id}` (`UI-03` slice 1, `DEL-01`). `204` has no body,
 * so success is `result.error === undefined`. Permanent: on success every
 * cached query for the analysis is removed (not invalidated — refetching a
 * deleted analysis would only 404). */
export function useDeleteAnalysis(analysisId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation<void, ApiCallError, void>({
    mutationFn: async () => {
      const result = await deleteAnalysisResourceApiV1AnalysesAnalysisIdDelete({
        path: { analysis_id: analysisId as string },
      })
      if (result.error) {
        throw new ApiCallError(result.error)
      }
    },
    onSuccess: () => {
      queryClient.removeQueries({
        predicate: (query) =>
          query.queryKey.length > 1 && query.queryKey[1] === analysisId,
      })
    },
  })
}
