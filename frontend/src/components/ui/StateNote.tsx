import type { ReactNode } from 'react'

export interface StateNoteProps {
  /** `loading` is announced politely; `empty` is plain text. Errors use `Alert`. */
  kind: 'loading' | 'empty'
  children: ReactNode
}

/** The one plain pattern for a supporting area that is loading or has nothing
 * to show (`UX-07`, D-075; `docs/ui-specification.md` §12.9). An empty area
 * says what is absent and never reads as a failure. */
export function StateNote({ kind, children }: StateNoteProps) {
  const className = 'mt-2 text-sm text-slate-600 dark:text-slate-400'
  if (kind === 'loading') {
    return (
      <p role="status" aria-live="polite" className={className}>
        {children}
      </p>
    )
  }
  return <p className={className}>{children}</p>
}
