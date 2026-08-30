import { useParams, useSearchParams } from 'react-router'
import { FindingSeverityBadge } from '../../components/provenance/FindingSeverityBadge'
import { filterFindings, sortFindingsByPriority } from '../../domain/finding'
import { useAnalysisFindings } from './api'

/** The Findings screen (`docs/ui-specification.md` §4.6). Filters/sort
 * are owned by URL search parameters (§6); filtering/sorting itself
 * happens client-side over the full list `GET .../findings` already
 * returns, since that endpoint takes no filter/sort query parameters
 * yet (`WP-025`'s Recorded assumption 5). */
export function FindingsRoute() {
  const { analysisId } = useParams<{ analysisId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const findingsQuery = useAnalysisFindings(analysisId)

  const severity = searchParams.get('severity') ?? ''
  const category = searchParams.get('category') ?? ''
  const search = searchParams.get('search') ?? ''

  if (findingsQuery.isLoading) {
    return (
      <p
        role="status"
        aria-live="polite"
        className="text-sm text-slate-600 dark:text-slate-400"
      >
        Loading findings…
      </p>
    )
  }

  if (findingsQuery.isError) {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-300">
        {findingsQuery.error.message}
      </p>
    )
  }

  const allFindings = findingsQuery.data?.items ?? []
  const filtered = filterFindings(allFindings, {
    severity: severity || undefined,
    category: category || undefined,
    search: search || undefined,
  })
  const sorted = sortFindingsByPriority(filtered)

  const severityOptions = Array.from(
    new Set(allFindings.map((finding) => finding.severity)),
  )
  const categoryOptions = Array.from(
    new Set(allFindings.map((finding) => finding.category)),
  ).sort()

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) {
      next.set(key, value)
    } else {
      next.delete(key)
    }
    setSearchParams(next)
  }

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
        Findings
      </h2>

      <form
        role="search"
        aria-label="Filter findings"
        className="flex flex-wrap items-end gap-4"
        onSubmit={(event) => event.preventDefault()}
      >
        <div className="flex flex-col gap-1">
          <label
            htmlFor="severity-filter"
            className="text-xs font-medium text-slate-600 dark:text-slate-400"
          >
            Severity
          </label>
          <select
            id="severity-filter"
            value={severity}
            onChange={(event) => updateParam('severity', event.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800"
          >
            <option value="">All</option>
            {severityOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label
            htmlFor="category-filter"
            className="text-xs font-medium text-slate-600 dark:text-slate-400"
          >
            Category
          </label>
          <select
            id="category-filter"
            value={category}
            onChange={(event) => updateParam('category', event.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800"
          >
            <option value="">All</option>
            {categoryOptions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label
            htmlFor="search-filter"
            className="text-xs font-medium text-slate-600 dark:text-slate-400"
          >
            Search
          </label>
          <input
            id="search-filter"
            type="search"
            value={search}
            onChange={(event) => updateParam('search', event.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-800"
          />
        </div>
      </form>

      <p className="text-sm text-slate-500 dark:text-slate-400">
        {sorted.length} of {allFindings.length} finding
        {allFindings.length === 1 ? '' : 's'}
      </p>

      {sorted.length === 0 ? (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          No findings match the current filters.
        </p>
      ) : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left dark:border-slate-800">
              <th scope="col" className="py-2 pr-4">
                Severity
              </th>
              <th scope="col" className="py-2 pr-4">
                Category
              </th>
              <th scope="col" className="py-2 pr-4">
                Observation
              </th>
              <th scope="col" className="py-2 pr-4">
                Affected rows
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((finding) => (
              <tr
                key={`${finding.detector_id}-${finding.calculated_observation}`}
                className="border-b border-slate-100 dark:border-slate-900"
              >
                <td className="py-2 pr-4">
                  <FindingSeverityBadge severity={finding.severity} />
                </td>
                <td className="py-2 pr-4">{finding.category}</td>
                <td className="py-2 pr-4">{finding.calculated_observation}</td>
                <td className="py-2 pr-4">{finding.affected_row_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
