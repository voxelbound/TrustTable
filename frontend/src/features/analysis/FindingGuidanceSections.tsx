import type {
  BusinessImpactStatementResponse,
  ProposedValidationRuleResponse,
} from '../../api'

/** The three advisory Finding Detail sections that follow the
 * explanation (`docs/ui-specification.md` §4.7; `AI-08`,
 * `docs/decision-log.md` D-040): possible business impact, remediation and
 * the proposed validation rule.
 *
 * Their content comes from one validated AI response when an AI
 * interpretation was accepted, and from TrustTable's deterministic built-in
 * guidance otherwise — both arrive in the same shape, so these components do
 * not care which, only that the *kind* of statement is always visible:
 *
 * - business impact is always a *potential* impact shown together with the
 *   condition it depends on, never as a fact. The badge is derived by the
 *   backend from what TrustTable can establish — "informed by your
 *   confirmed context" when a statement cites context you confirmed, and
 *   "conditional" otherwise. There is deliberately no "evidence-backed"
 *   badge: the deterministic evidence establishes what was found in the
 *   data, not what it costs your business, and a model's prose cannot award
 *   itself that standing;
 * - remediation is advisory: TrustTable never changes uploaded data;
 * - the validation rule is a proposal, never an active or authoritative
 *   rule.
 *
 * Nothing here injects raw HTML; every string (which may embed untrusted
 * column names or model text) is rendered as plain text. */

const SECTION_HEADING =
  'text-xl font-semibold text-slate-900 dark:text-slate-100'
const NOTE = 'mt-1 text-xs text-slate-500 dark:text-slate-400'
const BADGE =
  'inline-block rounded px-1.5 py-0.5 text-xs font-medium whitespace-nowrap'

const BASIS_LABEL: Record<BusinessImpactStatementResponse['basis'], string> = {
  confirmed_context: 'Informed by your confirmed context',
  assumption: 'Conditional',
}

const BASIS_STYLE: Record<BusinessImpactStatementResponse['basis'], string> = {
  confirmed_context:
    'bg-sky-100 text-sky-900 dark:bg-sky-900/40 dark:text-sky-200',
  assumption:
    'bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200',
}

const RULE_TYPE_LABEL: Record<string, string> = {
  not_null: 'Not null',
  unique: 'Unique',
  accepted_values: 'Accepted values',
  numeric_range: 'Numeric range',
  date_range: 'Date range',
  regex: 'Pattern (regex)',
  max_missing_percentage: 'Maximum missing percentage',
  approximate_equality: 'Approximate equality',
  expression_comparison: 'Expression comparison',
  conditional_rule: 'Conditional rule',
  max_duplicate_percentage: 'Maximum duplicate percentage',
}

function humanize(identifier: string): string {
  return identifier.replace(/_/g, ' ')
}

export interface SourceProps {
  /** `true` when an accepted AI interpretation produced the section. */
  aiAssisted: boolean
}

export interface BusinessImpactSectionProps extends SourceProps {
  statements: readonly BusinessImpactStatementResponse[]
}

/** "Possible business impact": one item per statement, each labelled with
 * the kind of support it has. */
export function BusinessImpactSection({
  statements,
  aiAssisted,
}: BusinessImpactSectionProps) {
  return (
    <section aria-labelledby="impact-heading">
      <h2 id="impact-heading" className={SECTION_HEADING}>
        Possible business impact
      </h2>
      <p className={NOTE}>
        {aiAssisted ? 'AI-assisted. ' : 'Built-in guidance. '}
        These are potential impacts, not established facts: the analysis shows
        what was found in your data, not what it costs your business. Each one
        states the condition it depends on.
      </p>
      {statements.length === 0 ? (
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          No business-impact statements were produced for this finding.
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-3">
          {statements.map((item, index) => (
            <li
              key={`${item.basis}-${index}`}
              className="rounded border border-slate-200 p-3 text-sm dark:border-slate-800"
            >
              <span className={`${BADGE} ${BASIS_STYLE[item.basis]}`}>
                {BASIS_LABEL[item.basis]}
              </span>
              <p className="mt-1 text-slate-800 dark:text-slate-200">
                {item.statement}
              </p>
              {item.assumption && (
                <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
                  Assumes: {item.assumption}
                </p>
              )}
              {item.basis === 'confirmed_context' &&
                item.context_fields.length > 0 && (
                  <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
                    Draws on your confirmed{' '}
                    {item.context_fields.map(humanize).join(', ')}
                  </p>
                )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export interface RemediationSectionProps extends SourceProps {
  steps: readonly string[]
}

/** "Remediation": advisory steps for a person. */
export function RemediationSection({
  steps,
  aiAssisted,
}: RemediationSectionProps) {
  return (
    <section aria-labelledby="remediation-heading">
      <h2 id="remediation-heading" className={SECTION_HEADING}>
        Remediation
      </h2>
      <p className={NOTE}>
        Advisory only — TrustTable never changes your uploaded data. Make any
        change in your own source system.
        {aiAssisted ? ' These suggestions were AI-assisted.' : ''}
      </p>
      {steps.length === 0 ? (
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          No remediation steps were produced for this finding.
        </p>
      ) : (
        <ol className="mt-2 flex list-decimal flex-col gap-2 pl-5 text-sm text-slate-800 dark:text-slate-200">
          {steps.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
      )}
    </section>
  )
}

export interface ValidationRuleSectionProps extends SourceProps {
  rule: ProposedValidationRuleResponse | null
}

/** "Validation rule": a proposal, explicitly not active. */
export function ValidationRuleSection({
  rule,
  aiAssisted,
}: ValidationRuleSectionProps) {
  return (
    <section aria-labelledby="rule-heading">
      <h2 id="rule-heading" className={SECTION_HEADING}>
        Validation rule
      </h2>
      {rule === null ? (
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          No validation rule was proposed for this finding.
        </p>
      ) : (
        <div className="mt-2 rounded border border-slate-200 p-3 text-sm dark:border-slate-800">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`${BADGE} bg-slate-200 text-slate-900 dark:bg-slate-700 dark:text-slate-100`}
            >
              Proposed — not active
            </span>
            <span className="text-xs text-slate-600 dark:text-slate-400">
              {RULE_TYPE_LABEL[rule.rule_type] ?? humanize(rule.rule_type)}
            </span>
          </div>
          <p className="mt-2 text-slate-800 dark:text-slate-200">
            {rule.description}
          </p>
          {rule.columns.length > 0 && (
            <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
              Applies to:{' '}
              {rule.columns.map((column) => column.original_name).join(', ')}
            </p>
          )}
          <p className={NOTE}>
            This is a suggestion only. TrustTable does not run or enforce it,
            and nothing is activated automatically.
            {aiAssisted ? ' The proposal was AI-assisted.' : ''}
          </p>
        </div>
      )}
    </section>
  )
}
