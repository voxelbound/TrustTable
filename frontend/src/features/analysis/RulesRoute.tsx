import { useState } from 'react'
import { useParams } from 'react-router'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import type { ValidationRuleResponse } from '../../api'
import {
  useDeleteRule,
  useDownloadRulesExport,
  useRules,
  useRunRule,
  type RulesExportFormat,
} from './api'

/** The supported parameters of a rule, in a fixed order, only the ones the
 * rule's type actually uses (the API sends `null` for the rest). Read-only:
 * no route edits a rule in place. */
const PARAMETER_FIELDS: {
  key: keyof ValidationRuleResponse
  label: string
}[] = [
  { key: 'minimum', label: 'Minimum' },
  { key: 'maximum', label: 'Maximum' },
  { key: 'minimum_date', label: 'Earliest date' },
  { key: 'maximum_date', label: 'Latest date' },
  { key: 'pattern', label: 'Pattern' },
  { key: 'accepted_values', label: 'Accepted values' },
  { key: 'comparison_operator', label: 'Comparison operator' },
  { key: 'comparison_value', label: 'Comparison value' },
  { key: 'condition_operator', label: 'Condition operator' },
  { key: 'condition_value', label: 'Condition value' },
  { key: 'threshold_percentage', label: 'Threshold percentage' },
  { key: 'tolerance', label: 'Tolerance' },
]

function formatParameter(value: unknown): string {
  return Array.isArray(value) ? value.join(', ') : String(value)
}

/** Saves text as a file through a temporary object URL. The text is never
 * inserted into the page. */
function saveFile(fileName: string, mimeType: string, text: string) {
  const url = URL.createObjectURL(
    new Blob([text], { type: `${mimeType};charset=utf-8` }),
  )
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

const EXPORT_MIME: Record<RulesExportFormat, string> = {
  json: 'application/json',
  yaml: 'application/yaml',
}

function RuleCard({
  rule,
  busy,
  onRun,
  onDelete,
}: {
  rule: ValidationRuleResponse
  busy: boolean
  onRun: () => void
  onDelete: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const detailsId = `rule-details-${rule.rule_id}`
  const result = rule.last_result
  const parameters = PARAMETER_FIELDS.filter(
    (field) => rule[field.key] !== null && rule[field.key] !== undefined,
  )

  return (
    <li className="rounded border border-slate-200 p-3 dark:border-slate-800">
      <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
        {rule.description}
      </p>
      <p className="text-xs text-slate-600 dark:text-slate-400">
        {rule.enabled ? 'Enabled' : 'Disabled'} · Severity {rule.severity} ·{' '}
        {rule.provenance}
      </p>
      {result === null ? (
        <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
          Not run yet.
        </p>
      ) : result.error !== null ? (
        <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
          The last run could not be completed: {result.error}
        </p>
      ) : (
        <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
          {result.pass_count} passed · {result.fail_count} failed ·{' '}
          {result.skipped_count} skipped
        </p>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          variant="secondary"
          aria-expanded={expanded}
          aria-controls={detailsId}
          aria-label={`${expanded ? 'Hide' : 'Show'} details of rule ${rule.description}`}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? 'Hide details' : 'Show details'}
        </Button>
        <Button
          variant="secondary"
          disabled={busy}
          aria-label={`Run rule ${rule.description}`}
          onClick={onRun}
        >
          Run rule
        </Button>
        <Button
          variant="secondary"
          disabled={busy}
          aria-label={`Delete rule ${rule.description}`}
          onClick={onDelete}
        >
          Delete rule
        </Button>
      </div>
      {expanded && (
        <div id={detailsId} className="mt-3 flex flex-col gap-3 text-sm">
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
            <dt className="font-medium">Rule type</dt>
            <dd className="break-all">{rule.rule_type}</dd>
            <dt className="font-medium">Scope</dt>
            <dd>{rule.scope}</dd>
            <dt className="font-medium">Columns</dt>
            <dd className="break-all">
              {rule.columns.map((column) => column.original_name).join(', ')}
            </dd>
            <dt className="font-medium">Null handling</dt>
            <dd>{rule.null_handling}</dd>
            {parameters.map((field) => (
              <div key={field.key} className="contents">
                <dt className="font-medium">{field.label}</dt>
                <dd className="break-all">
                  {formatParameter(rule[field.key])}
                </dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-slate-600 dark:text-slate-400">
            Parameters are shown read-only. To change a rule, delete it and
            create it again.
          </p>
          {result !== null && result.example_failures.length > 0 && (
            <div>
              <p className="font-medium">Example failures</p>
              <ul className="mt-1 list-disc pl-5">
                {result.example_failures.map((example) => (
                  <li key={`${example.row_number}-${example.reason}`}>
                    Row {example.row_number}: {example.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

/** The Rules screen (`docs/ui-specification.md` §4.9; `UI-03` slice 3).
 * Lists the analysis's validation rules with their latest results, lets
 * the manager re-run or delete a rule, and downloads the validated-rules
 * export. Rule and failure text is untrusted and only ever rendered as
 * escaped text. */
export function RulesRoute() {
  const { analysisId } = useParams<{ analysisId: string }>()
  const rulesQuery = useRules(analysisId)
  const runMutation = useRunRule(analysisId)
  const deleteMutation = useDeleteRule(analysisId)
  const exportMutation = useDownloadRulesExport(analysisId)
  const [pendingDelete, setPendingDelete] =
    useState<ValidationRuleResponse | null>(null)

  const rules = rulesQuery.data?.items ?? []
  const busy =
    runMutation.isPending ||
    deleteMutation.isPending ||
    exportMutation.isPending
  const actionError =
    runMutation.error ?? deleteMutation.error ?? exportMutation.error

  const handleExport = (format: RulesExportFormat) => {
    exportMutation.mutate(format, {
      onSuccess: (text) =>
        saveFile(
          `rules-${analysisId ?? 'analysis'}.${format}`,
          EXPORT_MIME[format],
          text,
        ),
    })
  }

  const handleConfirmDelete = () => {
    if (pendingDelete === null) return
    deleteMutation.mutate(pendingDelete.rule_id, {
      onSettled: () => setPendingDelete(null),
    })
  }

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="rules-heading">
        <h2
          id="rules-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Validation rules
        </h2>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          Rules describe checks your data should satisfy. TrustTable runs them
          against this dataset only; it never changes your data or enforces a
          rule anywhere else.
        </p>
        {rulesQuery.isLoading ? (
          <p
            role="status"
            aria-live="polite"
            className="mt-2 text-sm text-slate-600 dark:text-slate-400"
          >
            Loading rules…
          </p>
        ) : rulesQuery.isError ? (
          <div className="mt-2">
            <Alert variant="error" title="Could not load rules">
              {rulesQuery.error.message}
            </Alert>
          </div>
        ) : rules.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            No validation rules exist for this analysis yet.
          </p>
        ) : (
          <ul className="mt-3 flex flex-col gap-3">
            {rules.map((rule) => (
              <RuleCard
                key={rule.rule_id}
                rule={rule}
                busy={busy}
                onRun={() => runMutation.mutate(rule.rule_id)}
                onDelete={() => setPendingDelete(rule)}
              />
            ))}
          </ul>
        )}
      </section>

      {actionError && (
        <Alert variant="error" title="That action could not be completed">
          {actionError.message}
        </Alert>
      )}

      <section aria-labelledby="rules-export-heading">
        <h2
          id="rules-export-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Export validated rules
        </h2>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          The export contains only enabled rules whose latest run completed
          without error, with counts only and no dataset rows.
        </p>
        <div className="mt-3 flex flex-wrap gap-3">
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => handleExport('json')}
          >
            Download JSON
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => handleExport('yaml')}
          >
            Download YAML
          </Button>
        </div>
      </section>

      {pendingDelete !== null && (
        <ConfirmDialog
          title="Delete this rule?"
          confirmLabel="Delete rule"
          pending={deleteMutation.isPending}
          onConfirm={handleConfirmDelete}
          onCancel={() => setPendingDelete(null)}
        >
          This removes the rule and its stored result from this analysis.
        </ConfirmDialog>
      )}
    </div>
  )
}
