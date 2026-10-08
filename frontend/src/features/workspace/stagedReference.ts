/**
 * Where the browser keeps the opaque reference to the file the user has
 * chosen but not yet run (`UX-02`, `docs/decision-log.md` D-068).
 *
 * The reference is a capability: it is never put in a URL, so it cannot reach
 * browser history, a referrer or a server log. It lives in `sessionStorage`
 * (tab-scoped, cleared when the tab closes), which lets a reload of the
 * Configure step continue. Storage can be unavailable or throw (private mode,
 * quota, disabled storage); every function then degrades to "no reference"
 * rather than failing.
 */

const STORAGE_KEY = 'trusttable.stagedUploadReference'

export function readStagedReference(): string | null {
  try {
    const value = window.sessionStorage.getItem(STORAGE_KEY)
    return value !== null && value !== '' ? value : null
  } catch {
    return null
  }
}

export function rememberStagedReference(reference: string): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, reference)
  } catch {
    // Without storage the Configure step cannot be resumed after a reload;
    // the file simply expires on the server.
  }
}

export function forgetStagedReference(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing to forget.
  }
}
