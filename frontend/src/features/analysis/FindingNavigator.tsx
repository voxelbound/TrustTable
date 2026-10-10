import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router'
import type { FindingNavigation } from '../../domain/findingNavigation'

export interface FindingNavigatorProps {
  analysisId: string
  navigation: FindingNavigation
  /** The carried filter search string (`?severity=...`), or empty. */
  search: string
  /** True when any filter narrows the list the reviewer is stepping through. */
  filtered: boolean
}

const LINK_CLASS =
  'rounded border border-slate-300 px-2 py-1 text-sm font-medium text-slate-900 ' +
  'hover:bg-slate-100 dark:border-slate-600 dark:text-slate-100 dark:hover:bg-slate-800'
const DISABLED_CLASS =
  'rounded border border-slate-200 px-2 py-1 text-sm text-slate-400 ' +
  'dark:border-slate-800 dark:text-slate-600'

/** True when a key press belongs to text entry or a form control, so a
 * review shortcut must not fire. Links and buttons are deliberately not
 * included: after following a navigation link the reviewer can keep going. */
function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false
  }
  if (target.isContentEditable) {
    return true
  }
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

/** Previous, next and next-unreviewed movement through the findings the
 * reviewer is looking at (`UX-05`, `docs/ui-specification.md` §12.2). The
 * list is the filtered, priority-ordered list from the Findings screen; the
 * navigation never wraps silently and says plainly when there is no further
 * finding. Keyboard shortcuts `p`, `n` and `u` are inert while typing in a
 * field or when a modifier key is held. */
export function FindingNavigator({
  analysisId,
  navigation,
  search,
  filtered,
}: FindingNavigatorProps) {
  const navigate = useNavigate()
  const base = `/analyses/${analysisId}/findings`
  const hrefFor = (findingId: string) => `${base}/${findingId}${search}`

  const { previousId, nextId, nextUnreviewedId, position, total } = navigation

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        isEditableTarget(event.target)
      ) {
        return
      }
      const targetId =
        event.key === 'p'
          ? previousId
          : event.key === 'n'
            ? nextId
            : event.key === 'u'
              ? nextUnreviewedId
              : null
      if (targetId) {
        event.preventDefault()
        void navigate(`${base}/${targetId}${search}`)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [navigate, base, search, previousId, nextId, nextUnreviewedId])

  const scope = filtered ? 'in the filtered list' : 'in this analysis'

  return (
    <nav
      aria-label="Move between findings"
      className="flex flex-col gap-2 rounded border border-slate-200 p-3 dark:border-slate-800"
    >
      <p className="text-sm text-slate-700 dark:text-slate-300">
        {position === null
          ? `This finding is not in the list the filters show (${total} finding${total === 1 ? '' : 's'} shown).`
          : `Finding ${position} of ${total} ${scope}.`}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {previousId ? (
          <Link
            to={hrefFor(previousId)}
            aria-keyshortcuts="p"
            className={LINK_CLASS}
          >
            Previous
          </Link>
        ) : (
          <span aria-disabled="true" className={DISABLED_CLASS}>
            Previous
          </span>
        )}
        {nextId ? (
          <Link
            to={hrefFor(nextId)}
            aria-keyshortcuts="n"
            className={LINK_CLASS}
          >
            Next
          </Link>
        ) : (
          <span aria-disabled="true" className={DISABLED_CLASS}>
            Next
          </span>
        )}
        {nextUnreviewedId ? (
          <Link
            to={hrefFor(nextUnreviewedId)}
            aria-keyshortcuts="u"
            className={LINK_CLASS}
          >
            Next unreviewed
          </Link>
        ) : (
          <span aria-disabled="true" className={DISABLED_CLASS}>
            Next unreviewed
          </span>
        )}
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400">
        {nextId === null && position !== null
          ? 'This is the last finding; there is no wrap-around. '
          : ''}
        {nextUnreviewedId === null ? 'No unreviewed finding follows. ' : ''}
        Keyboard: P previous, N next, U next unreviewed.
      </p>
    </nav>
  )
}
