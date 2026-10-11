import { useSyncExternalStore } from 'react'

/**
 * Advanced mode (`UX-08b`, `docs/decision-log.md` D-066 item 5 and D-077): a
 * display preference kept in this browser only. It decides whether technical
 * detail is shown (the Technical details area and the runtime and model
 * configuration on the Settings screen). It is not a setting of the product
 * and not an access control: nothing is sent to the server, and the server
 * answers the same requests whatever the preference is.
 *
 * Default is Normal. If the browser refuses storage, the choice is held for
 * this page only and Normal applies again after a reload.
 */
const STORAGE_KEY = 'trusttable.advanced-mode'

let held = false
const listeners = new Set<() => void>()

function read(): boolean {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'true') return true
    if (stored === 'false') return false
  } catch {
    // Storage is unavailable; the value held for this page applies.
  }
  return held
}

function notify() {
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  // Another tab changing the preference arrives as a storage event.
  window.addEventListener('storage', notify)
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) {
      window.removeEventListener('storage', notify)
    }
  }
}

/** Sets the preference for this browser. */
export function setAdvancedMode(enabled: boolean): void {
  held = enabled
  try {
    window.localStorage.setItem(STORAGE_KEY, enabled ? 'true' : 'false')
  } catch {
    // Not persisted; the value is held for this page.
  }
  notify()
}

/** Whether Advanced mode is on, and a way to change it. */
export function useAdvancedMode(): readonly [
  boolean,
  (enabled: boolean) => void,
] {
  const enabled = useSyncExternalStore(subscribe, read, () => false)
  return [enabled, setAdvancedMode] as const
}
