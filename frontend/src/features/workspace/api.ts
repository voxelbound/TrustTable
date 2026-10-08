/**
 * TanStack Query hooks for the Workspace and Configure step (`UX-02`,
 * `docs/decision-log.md` D-068): the Local AI status and the staged-upload
 * routes. Pure client-side composition of the generated SDK
 * (`docs/architecture.md` §4). The staged reference is only ever sent in a
 * request body, never in a URL.
 */

import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import {
  getAiStatusApiV1AiStatusGet,
  postStagedUploadApiV1StagedUploadsPost,
  postStagedUploadDiscardApiV1StagedUploadsDiscardPost,
  postStagedUploadInspectApiV1StagedUploadsInspectPost,
  postStagedUploadRunApiV1StagedUploadsRunPost,
  type AiStatusResponse,
  type StagedUploadResponse,
  type UploadAnalysisResponse,
} from '../../api'
import { ApiCallError } from '../analysis/api'

const AI_STATUS_STALE_MS = 10_000

/** `GET /ai/status`. Never retried automatically: the route already makes one
 * bounded probe, and an unavailable runtime is a valid, displayable answer. */
export function useAiStatus() {
  return useQuery<AiStatusResponse, ApiCallError>({
    queryKey: ['ai-status'],
    queryFn: async () => {
      const result = await getAiStatusApiV1AiStatusGet()
      if (result.data === undefined) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    staleTime: AI_STATUS_STALE_MS,
    retry: false,
    refetchOnWindowFocus: false,
  })
}

/** `POST /staged-uploads`: stages the chosen file. Starts no analysis. A file
 * that cannot be read at all is a successful response with `staging_ref: null`
 * and `problems`; request-level refusals (type, size, full) are errors. */
export function useStageUpload() {
  return useMutation<StagedUploadResponse, ApiCallError, File>({
    mutationFn: async (file: File) => {
      const result = await postStagedUploadApiV1StagedUploadsPost({
        body: { file },
      })
      if (result.data === undefined) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
  })
}

/** `POST /staged-uploads/inspect`: the staged file's facts, optionally for
 * one worksheet. Read-only on the server; an expired or used reference is
 * `410 STAGED_UPLOAD_UNAVAILABLE`. The previous result stays on screen while
 * another worksheet is inspected. */
export function useStagedUpload(
  reference: string | null,
  worksheet: string | null,
) {
  return useQuery<StagedUploadResponse, ApiCallError>({
    queryKey: ['staged-upload', reference, worksheet],
    enabled: reference !== null,
    queryFn: async () => {
      const result = await postStagedUploadInspectApiV1StagedUploadsInspectPost(
        {
          body: { staging_ref: reference ?? '', worksheet },
        },
      )
      if (result.data === undefined) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    placeholderData: keepPreviousData,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  })
}

export interface RunStagedUploadRequest {
  reference: string
  worksheet: string | null
}

/** `POST /staged-uploads/run`: analyses exactly the staged bytes. */
export function useRunStagedUpload() {
  return useMutation<
    UploadAnalysisResponse,
    ApiCallError,
    RunStagedUploadRequest
  >({
    mutationFn: async ({ reference, worksheet }) => {
      const result = await postStagedUploadRunApiV1StagedUploadsRunPost({
        body: { staging_ref: reference, worksheet },
      })
      if (result.data === undefined) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
  })
}

/** `POST /staged-uploads/discard`: always succeeds on the server (`204`),
 * whether or not the file still existed. */
export function useDiscardStagedUpload() {
  return useMutation<void, ApiCallError, string>({
    mutationFn: async (reference: string) => {
      const result = await postStagedUploadDiscardApiV1StagedUploadsDiscardPost(
        { body: { staging_ref: reference } },
      )
      if (result.error !== undefined) {
        throw new ApiCallError(result.error)
      }
    },
  })
}
