import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'

/** The visible but disabled *Compare datasets* area (`UX-02`,
 * `docs/decision-log.md` D-066 item 3, D-068). Comparison is planned and not
 * implemented, so the control is genuinely disabled and the text says so in
 * words: nothing unbuilt is presented as available
 * (`docs/ui-specification.md` §12.1). */
export function CompareDatasetsPanel() {
  return (
    <section
      aria-labelledby="compare-heading"
      className="rounded border border-dashed border-slate-300 p-4 dark:border-slate-700"
    >
      <div className="flex items-center gap-2">
        <h2
          id="compare-heading"
          className="text-base font-medium text-slate-900 dark:text-slate-100"
        >
          Compare datasets
        </h2>
        <Badge tone="info">Planned</Badge>
      </div>
      <p
        id="compare-description"
        className="mt-2 text-sm text-slate-600 dark:text-slate-400"
      >
        Comparing two datasets is planned and is not available yet.
      </p>
      <Button
        variant="secondary"
        className="mt-3"
        disabled
        aria-describedby="compare-description"
      >
        Compare datasets
      </Button>
    </section>
  )
}
