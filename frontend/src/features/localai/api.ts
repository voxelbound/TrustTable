/**
 * TanStack Query hooks for the Local AI screen (`UX-09`, `docs/decision-log.md`
 * D-078): the generated client for `GET /ai/readiness` and
 * `POST /ai/connection-test`. Neither request carries any input: the browser
 * never names an address, a model or a path, and nothing is shown that the
 * server did not return.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getAiReadinessApiV1AiReadinessGet,
  postAiConnectionTestApiV1AiConnectionTestPost,
  type AiConnectionTestResponse,
  type AiReadinessResponse,
} from '../../api'
import { ApiCallError } from '../analysis/api'

const READINESS_KEY = ['ai-readiness'] as const

/** `GET /ai/readiness`. Always fetched when the screen opens, and never retried
 * automatically: the route makes at most one short probe, and a runtime that
 * does not answer is a valid, displayable answer. */
export function useAiReadiness() {
  return useQuery<AiReadinessResponse, ApiCallError>({
    queryKey: READINESS_KEY,
    queryFn: async () => {
      const result = await getAiReadinessApiV1AiReadinessGet()
      if (result.data === undefined) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  })
}

/** `POST /ai/connection-test`: checks once whether the configured runtime
 * answers. The checklist is refreshed afterwards so it never contradicts the
 * answer, and the shared AI status is refreshed for the same reason. */
export function useConnectionTest() {
  const queryClient = useQueryClient()
  return useMutation<AiConnectionTestResponse, ApiCallError, void>({
    mutationFn: async () => {
      const result = await postAiConnectionTestApiV1AiConnectionTestPost()
      if (result.data === undefined) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    onSuccess: (data) => {
      // A refused test probed nothing, so there is nothing new to reflect.
      if (data.tested) {
        void queryClient.invalidateQueries({ queryKey: READINESS_KEY })
        void queryClient.invalidateQueries({ queryKey: ['ai-status'] })
      }
    },
  })
}
