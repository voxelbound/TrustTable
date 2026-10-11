import { useState } from 'react'

/** State and constants the inspector screens share (`UX-06`, D-073 and
 * D-074). Kept apart from the components so that file only exports
 * components. */

export const INITIAL_WINDOW = 5
export const EXPAND_STEP = 10
/** The server's own per-side maximum is authoritative (`max_window` in the
 * response); this only bounds what the screen asks for before it knows it. */
export const CLIENT_MAX_WINDOW = 25
export const ROW_PARAM = 'row'

export interface WindowSize {
  before: number
  after: number
}

/** The window size the reader has asked for, and the control that widens it. */
export function useWindowSize() {
  const [windowSize, setWindowSize] = useState<WindowSize>({
    before: INITIAL_WINDOW,
    after: INITIAL_WINDOW,
  })
  const widen = (maxWindow: number) =>
    setWindowSize((current) => ({
      before: Math.min(
        current.before + EXPAND_STEP,
        maxWindow || CLIENT_MAX_WINDOW,
      ),
      after: Math.min(
        current.after + EXPAND_STEP,
        maxWindow || CLIENT_MAX_WINDOW,
      ),
    }))
  return { windowSize, widen }
}

/** The set of values the reader has chosen to see in full. */
export function useRevealed() {
  const [revealed, setRevealed] = useState<ReadonlySet<string>>(new Set())
  return {
    revealed,
    reveal: (key: string) =>
      setRevealed((current) => new Set(current).add(key)),
  }
}

export function rowHref(row: number, carriedFilters: URLSearchParams): string {
  const params = new URLSearchParams(carriedFilters)
  params.set(ROW_PARAM, String(row))
  return `?${params.toString()}`
}
