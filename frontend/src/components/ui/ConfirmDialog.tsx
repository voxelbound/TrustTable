import {
  useEffect,
  useId,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import { Button } from './Button'

export interface ConfirmDialogProps {
  title: string
  children: ReactNode
  confirmLabel: string
  cancelLabel?: string
  pending?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Accessible confirmation dialog primitive (`docs/ui-specification.md`
 * §5 "Dialog"). `role="alertdialog"` with a labelled title and described
 * body; focus starts on the safe (cancel) action, Escape cancels, and Tab
 * is kept inside the dialog. Destructive callers must use this rather than
 * acting on a single click. */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel = 'Cancel',
  pending = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId()
  const bodyId = useId()
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    rootRef.current?.querySelector<HTMLElement>('[data-cancel]')?.focus()
    return () => previous?.focus?.()
  }, [])

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape' && !pending) {
      event.stopPropagation()
      onCancel()
      return
    }
    if (event.key !== 'Tab') {
      return
    }
    const focusable = rootRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled])',
    )
    if (!focusable || focusable.length === 0) {
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div
        ref={rootRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        onKeyDown={handleKeyDown}
        className="w-full max-w-md rounded bg-white p-6 text-slate-900 shadow-lg dark:bg-slate-900 dark:text-slate-100"
      >
        <h2 id={titleId} className="text-lg font-semibold">
          {title}
        </h2>
        <div id={bodyId} className="mt-2 text-sm">
          {children}
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <Button
            variant="secondary"
            onClick={onCancel}
            disabled={pending}
            data-cancel="true"
          >
            {cancelLabel}
          </Button>
          <Button onClick={onConfirm} disabled={pending}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
