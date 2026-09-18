import { useState } from 'react'
import { useParams } from 'react-router'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import {
  useAnalysisContext,
  useAnswerGuidedQuestion,
  useConfirmContextFields,
  useFinalizeContext,
  useGuidedQuestions,
} from './api'
import type { ContextFieldValueResponse, ContextResponse } from '../../api'

/** The five single-value fields `PUT .../context` accepts edits for
 * (`analysis.service._EDITABLE_CONTEXT_FIELDS`, `API-02`) — the four
 * remaining fields are column-role lists, shown read-only below. */
const EDITABLE_FIELDS: { key: keyof ContextResponse; label: string }[] = [
  { key: 'probable_domain', label: 'Domain' },
  { key: 'row_grain', label: 'Row grain' },
  { key: 'primary_entity', label: 'Primary entity' },
  { key: 'currency_behavior', label: 'Currency behavior' },
  { key: 'expected_business_rules', label: 'Expected business rules' },
]

const ROLE_FIELDS: { key: keyof ContextResponse; label: string }[] = [
  { key: 'candidate_keys', label: 'Candidate keys' },
  { key: 'business_dates', label: 'Business dates' },
  { key: 'measure_roles', label: 'Measure roles' },
  { key: 'dimensions', label: 'Dimensions' },
]

/** The five-value provenance display `docs/ui-specification.md` §4.4
 * requires. */
const PROVENANCE_LABELS: Record<string, string> = {
  calculated: 'Calculated',
  ai_interpretation: 'AI interpretation',
  user_confirmed: 'Confirmed by user',
  user_corrected: 'Corrected by user',
  deterministic_fallback: 'Deterministic fallback',
}

function provenanceLabel(source: string): string {
  return PROVENANCE_LABELS[source] ?? source
}

function displayValue(field: ContextFieldValueResponse): string {
  return Array.isArray(field.value) ? field.value.join(', ') : field.value
}

/** The Context screen (`docs/ui-specification.md` §4.4; `API-02`,
 * `UI-02` slice 2, `WP-064`). Reachable after analysis completion,
 * alongside Overview/Findings — not a blocking pre-step (`docs/
 * decision-log.md` D-037's two-phase model).
 *
 * `docs/ui-specification.md` §4.4's own field list ("domain, row grain,
 * transaction key, business date, revenue measure, currency behavior,
 * negative quantity behavior") predates the real, implemented
 * `DatasetContext` domain model (`CTX-01`) and does not map one-to-one
 * onto it. This screen surfaces the real nine `ContextField` values
 * instead: the five single-value fields `API-02`'s own
 * `_EDITABLE_CONTEXT_FIELDS` supports editing, plus the four
 * column-role fields shown read-only (the backend structurally rejects
 * edits to those — `ContextFieldNotEditableError`) — a disclosed,
 * reversible interpretation, not a silent scope change. */
export function ContextRoute() {
  const { analysisId } = useParams<{ analysisId: string }>()
  const contextQuery = useAnalysisContext(analysisId)
  const questionsQuery = useGuidedQuestions(analysisId)
  const confirmFields = useConfirmContextFields(analysisId)
  const answerQuestion = useAnswerGuidedQuestion(analysisId)
  const finalizeContext = useFinalizeContext(analysisId)

  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [freeTextAnswers, setFreeTextAnswers] = useState<
    Record<string, string>
  >({})

  if (contextQuery.isLoading || questionsQuery.isLoading) {
    return (
      <p
        role="status"
        aria-live="polite"
        className="text-sm text-slate-600 dark:text-slate-400"
      >
        Loading context…
      </p>
    )
  }

  if (contextQuery.isError) {
    return (
      <Alert variant="error" title="Could not load context">
        {contextQuery.error.message}
      </Alert>
    )
  }

  if (questionsQuery.isError) {
    return (
      <Alert variant="error" title="Could not load guided questions">
        {questionsQuery.error.message}
      </Alert>
    )
  }

  const context = contextQuery.data
  const questions = questionsQuery.data?.items ?? []
  if (!context) {
    return null
  }

  const saveField = (fieldKey: string) => {
    const draft = drafts[fieldKey]
    if (draft === undefined) {
      return
    }
    confirmFields.mutate({
      edits: { [fieldKey]: draft },
      expectedVersion: context.context_version,
    })
  }

  const submitAnswer = (questionId: string, answerText: string) => {
    if (!answerText) {
      return
    }
    answerQuestion.mutate({
      questionId,
      answerText,
      expectedVersion: context.context_version,
    })
  }

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="context-heading">
        <h2
          id="context-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Context
        </h2>

        {confirmFields.isError && (
          <div className="mt-2">
            <Alert variant="error" title="Could not save context">
              {confirmFields.error.message}
            </Alert>
          </div>
        )}

        <dl className="mt-2 flex flex-col gap-4">
          {EDITABLE_FIELDS.map(({ key, label }) => {
            const field = context[key] as ContextFieldValueResponse
            return (
              <div key={key}>
                <dt className="font-medium text-slate-900 dark:text-slate-100">
                  {label}
                </dt>
                <dd className="mt-1 flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    aria-label={label}
                    defaultValue={displayValue(field)}
                    onChange={(event) =>
                      setDrafts((prev) => ({
                        ...prev,
                        [key]: event.target.value,
                      }))
                    }
                    className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900"
                  />
                  <Button
                    variant="secondary"
                    onClick={() => saveField(key)}
                    disabled={confirmFields.isPending}
                  >
                    Save
                  </Button>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {provenanceLabel(field.inference_source)}
                  </span>
                </dd>
              </div>
            )
          })}
        </dl>
      </section>

      <section aria-labelledby="context-roles-heading">
        <h2
          id="context-roles-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Detected roles
        </h2>
        <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm text-slate-700 dark:text-slate-300">
          {ROLE_FIELDS.map(({ key, label }) => {
            const field = context[key] as ContextFieldValueResponse
            return (
              <div key={key} className="contents">
                <dt className="font-medium">{label}</dt>
                <dd>
                  {displayValue(field) || '—'} (
                  {provenanceLabel(field.inference_source)})
                </dd>
              </div>
            )
          })}
        </dl>
      </section>

      <section aria-labelledby="questions-heading">
        <h2
          id="questions-heading"
          className="text-xl font-semibold text-slate-900 dark:text-slate-100"
        >
          Guided questions
        </h2>

        {answerQuestion.isError && (
          <div className="mt-2">
            <Alert variant="error" title="Could not save your answer">
              {answerQuestion.error.message}
            </Alert>
          </div>
        )}

        {questions.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            No open questions — everything is either confirmed or has a
            deterministic default.
          </p>
        ) : (
          <ul className="mt-2 flex flex-col gap-4">
            {questions.map((question) => (
              <li
                key={question.question_id}
                className="rounded border border-slate-200 p-3 dark:border-slate-800"
              >
                <p className="font-medium text-slate-900 dark:text-slate-100">
                  {question.concise_text}
                </p>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                  {question.explanation}
                </p>
                {question.answered_state === 'answered' ? (
                  <p className="mt-2 text-sm text-emerald-700 dark:text-emerald-400">
                    Answered.
                  </p>
                ) : (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {question.suggested_answers.map((suggested) => (
                      <Button
                        key={suggested}
                        variant="secondary"
                        onClick={() =>
                          submitAnswer(question.question_id, suggested)
                        }
                        disabled={answerQuestion.isPending}
                      >
                        {suggested}
                      </Button>
                    ))}
                    {question.free_text_allowed && (
                      <>
                        <input
                          type="text"
                          aria-label={`Free-text answer for: ${question.concise_text}`}
                          value={freeTextAnswers[question.question_id] ?? ''}
                          onChange={(event) =>
                            setFreeTextAnswers((prev) => ({
                              ...prev,
                              [question.question_id]: event.target.value,
                            }))
                          }
                          className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900"
                        />
                        <Button
                          variant="secondary"
                          onClick={() =>
                            submitAnswer(
                              question.question_id,
                              freeTextAnswers[question.question_id] ?? '',
                            )
                          }
                          disabled={answerQuestion.isPending}
                        >
                          Answer
                        </Button>
                      </>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="finalize-heading">
        <h2 id="finalize-heading" className="sr-only">
          Finalize context
        </h2>

        {finalizeContext.isError && (
          <div className="mb-2">
            <Alert variant="error" title="Could not finalize context">
              {finalizeContext.error.message}
            </Alert>
          </div>
        )}
        {finalizeContext.isSuccess && (
          <div className="mb-2">
            <Alert variant="success">Context finalized.</Alert>
          </div>
        )}

        <Button
          onClick={() =>
            finalizeContext.mutate({
              expectedVersion: context.context_version,
            })
          }
          disabled={finalizeContext.isPending}
        >
          Finalize context
        </Button>
      </section>
    </div>
  )
}
