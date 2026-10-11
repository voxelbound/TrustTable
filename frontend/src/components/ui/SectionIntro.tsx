import type { ReactNode } from 'react'

export interface SectionIntroProps {
  /** The area's name, shown as its heading. */
  title: string
  /** The area it belongs to in the workflow (`Review` or `Act and Export`). */
  group: 'Review' | 'Act and Export'
  /** What the area is for. */
  purpose: ReactNode
  /** When it can be used, and what it needs. */
  availability: ReactNode
  /** Why a manager would look at it. */
  why: ReactNode
  /** What to do next from here. */
  next: ReactNode
}

/** The opening of a supporting area (`UX-07`, D-075; `docs/ui-specification.md`
 * §12.2 and §12.9): where the area sits, what it is for, when it is available,
 * why it matters and what to do next, in plain words. It states only what the
 * area really does; it never describes a capability the product does not have. */
export function SectionIntro({
  title,
  group,
  purpose,
  availability,
  why,
  next,
}: SectionIntroProps) {
  const headingId = `intro-${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
  return (
    <section
      aria-labelledby={headingId}
      className="rounded border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {group}
      </p>
      <h2
        id={headingId}
        className="text-xl font-semibold text-slate-900 dark:text-slate-100"
      >
        {title}
      </h2>
      <p className="mt-2 text-sm text-slate-700 dark:text-slate-300">
        {purpose}
      </p>
      <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm text-slate-700 dark:text-slate-300">
        <dt className="font-medium">When it is available</dt>
        <dd>{availability}</dd>
        <dt className="font-medium">Why it matters</dt>
        <dd>{why}</dd>
        <dt className="font-medium">Next step</dt>
        <dd>{next}</dd>
      </dl>
    </section>
  )
}
