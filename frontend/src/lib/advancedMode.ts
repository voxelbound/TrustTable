import { useSyncExternalStore } from 'react'

/**
 * Advanced mode (`UX-08b`, `docs/decision-log.md` D-066 item 5 and D-077): a
 * display preference kept in this browser only. It decides whether technical
 * detail is shown (the Technical details area and the runtime and model
 * configuration on the Settings screen). It is not a setting of the product
 * and not an access control: nothing is sent to the server, and the server
 * answers the same requests whatever the preference is.
 *
 * Default is Normal. If the browser refuses to read or to write storage, the
 * choice is held for this page only and the page still shows the mode that was
 * chosen; the stored value (Normal by default) applies again after a reload.
 */
const STORAGE_KEY = 'trusttable.advanced-mode'

let held = false
// True after a write that storage refused: the page's own choice then outranks
// whatever storage still holds, so the page never shows a mode that was not the
// one chosen. It lasts until the choice is persisted or another tab changes it.
let heldAuthoritative = false
const listeners = new Set<() => void>()

function read(): boolean {
  if (heldAuthoritative) return held
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

// Another tab changing the preference arrives as a storage event; storage is
// then the newer truth.
function onStorage() {
  heldAuthoritative = false
  notify()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  window.addEventListener('storage', onStorage)
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) {
      window.removeEventListener('storage', onStorage)
    }
  }
}

/** Sets the preference for this browser. The page reflects the choice at once,
 * whether or not storage accepts it. */
export function setAdvancedMode(enabled: boolean): void {
  held = enabled
  try {
    window.localStorage.setItem(STORAGE_KEY, enabled ? 'true' : 'false')
    heldAuthoritative = false
  } catch {
    // Not persisted: the choice holds for this page and is lost on reload.
    heldAuthoritative = true
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
