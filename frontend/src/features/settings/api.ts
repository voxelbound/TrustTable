/**
 * TanStack Query hooks for the Settings screen (`UX-08b`,
 * `docs/decision-log.md` D-077): the generated client for the Settings API
 * built by `UX-08a` (D-076, `docs/api-specification.md` §4). Nothing here is
 * optimistic: a value is shown only as the server returned it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getAdvancedSettingsApiV1SettingsAdvancedGet,
  getSettingsRouteApiV1SettingsGet,
  putSettingApiV1SettingsKeyPut,
  resetSettingApiV1SettingsKeyDelete,
  type AdvancedSettingsResponse,
  type SettingItemResponse,
  type SettingsResponse,
} from '../../api'
import { ApiCallError } from '../analysis/api'

const SETTINGS_KEY = ['settings'] as const
const ADVANCED_KEY = ['settings', 'advanced'] as const

/** `GET /settings`. Always fetched when the screen opens, so a value changed
 * elsewhere is never shown stale. */
export function useSettings() {
  return useQuery<SettingsResponse, ApiCallError>({
    queryKey: SETTINGS_KEY,
    queryFn: async () => {
      const result = await getSettingsRouteApiV1SettingsGet()
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

/** `GET /settings/advanced`: the one response with runtime and model
 * configuration. It is requested only while `enabled`, which the caller sets
 * from Advanced mode, so Normal mode never asks for it. */
export function useAdvancedSettings(enabled: boolean) {
  return useQuery<AdvancedSettingsResponse, ApiCallError>({
    queryKey: ADVANCED_KEY,
    queryFn: async () => {
      const result = await getAdvancedSettingsApiV1SettingsAdvancedGet()
      if (result.data === undefined) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    enabled,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  })
}

function useAfterChange() {
  const queryClient = useQueryClient()
  return {
    /** Replaces the item with the one the server returned, and refreshes what
     * follows the effective value. */
    applied(item: SettingItemResponse) {
      queryClient.setQueryData<SettingsResponse>(SETTINGS_KEY, (current) => ({
        settings: (current?.settings ?? []).some((s) => s.key === item.key)
          ? (current?.settings ?? []).map((s) =>
              s.key === item.key ? item : s,
            )
          : [...(current?.settings ?? []), item],
      }))
      void queryClient.invalidateQueries({ queryKey: ADVANCED_KEY })
      void queryClient.invalidateQueries({ queryKey: ['ai-status'] })
    },
    /** After a refused change, fetch what the server holds now. */
    refresh() {
      void queryClient.invalidateQueries({ queryKey: SETTINGS_KEY })
      void queryClient.invalidateQueries({ queryKey: ['ai-status'] })
    },
  }
}

export interface WriteSettingInput {
  key: SettingItemResponse['key']
  value: boolean
  expectedVersion: number
}

/** `PUT /settings/{key}` with the version the screen was showing. */
export function useWriteSetting() {
  const after = useAfterChange()
  return useMutation<SettingItemResponse, ApiCallError, WriteSettingInput>({
    mutationFn: async ({ key, value, expectedVersion }) => {
      const result = await putSettingApiV1SettingsKeyPut({
        path: { key },
        body: { value, expected_version: expectedVersion },
      })
      if (result.data === undefined) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    onSuccess: (item) => after.applied(item),
    onError: () => after.refresh(),
  })
}

export interface ResetSettingInput {
  key: SettingItemResponse['key']
  expectedVersion: number
}

/** `DELETE /settings/{key}`: removes the stored value so the default applies. */
export function useResetSetting() {
  const after = useAfterChange()
  return useMutation<SettingItemResponse, ApiCallError, ResetSettingInput>({
    mutationFn: async ({ key, expectedVersion }) => {
      const result = await resetSettingApiV1SettingsKeyDelete({
        path: { key },
        query: { expected_version: expectedVersion },
      })
      if (result.data === undefined) {
        throw new ApiCallError(result.error)
      }
      return result.data
    },
    onSuccess: (item) => after.applied(item),
    onError: () => after.refresh(),
  })
}
