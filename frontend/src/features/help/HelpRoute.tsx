import { AppShell } from '../../components/layout/AppShell'

const HEADING = 'text-xl font-semibold text-slate-900 dark:text-slate-100'
const BODY = 'mt-2 text-sm text-slate-700 dark:text-slate-300'

interface Topic {
  id: string
  title: string
  body: string[]
}

/** What each term means, in business words (`UX-07`, D-075;
 * `docs/ui-specification.md` §12.1 and §12.9). Every statement describes what
 * the product does today. Nothing here says that TrustTable proves the data is
 * correct, that AI checks the data, or that anything is applied to other files. */
const TOPICS: Topic[] = [
  {
    id: 'findings-and-observations',
    title: 'Findings and observations',
    body: [
      'A finding is a data-quality concern that TrustTable’s checks identified. It has a severity and a confidence, an explanation of what was seen and where, and it counts toward the trust assessment. A finding says that something deserves a look, not that the data is wrong.',
      'An observation is a pattern seen in the data that is worth knowing. It has no severity, never changes the trust assessment and does not say that anything is wrong. Observations are listed apart from findings, under Worth knowing.',
    ],
  },
  {
    id: 'trust-assessment',
    title: 'The trust assessment',
    body: [
      'The trust assessment is a label and a score from 0 to 100 that sums up how far the findings suggest the file can be relied on for decisions. It is worked out by fixed rules from the findings, not by AI.',
      'It covers only what TrustTable’s checks look for. A high result means the checks found little to raise. It does not prove that the data is correct.',
    ],
  },
  {
    id: 'provenance',
    title: 'Where a statement comes from',
    body: [
      'Calculated: worked out from your file by TrustTable’s own checks, the same way every time.',
      'Deterministic fallback: a default TrustTable chose by fixed rules because nothing more specific was available.',
      'AI interpretation: a suggestion from the AI model, shown only when a model is set up. It is a suggestion, not a verified fact, and its source is shown with it.',
      'Confirmed by user and Corrected by user: you accepted the value, or you changed it. Your answer is used from then on.',
      'Where a source is shown, it describes how a statement was produced. It does not say that the statement is right.',
    ],
  },
  {
    id: 'sampled-and-full',
    title: 'Sampled and full',
    body: [
      'Technical details say whether the column profile covered every row (full data) or only some of them (sampled). A sampled profile describes only the rows it covered, and the number covered is shown.',
    ],
  },
  {
    id: 'ai',
    title: 'AI assistance',
    body: [
      'AI is optional and separate. The checks, findings, the trust assessment and the built-in guidance are ready without it and never wait for it.',
      'An AI explanation is requested for one finding at a time, and only when a model is set up. When it is not available, the built-in guidance is shown and says so.',
    ],
  },
  {
    id: 'rules',
    title: 'Rules',
    body: [
      'Rules are checks associated with this analysis. You can run them again, delete them and export those that ran without error, so that the team who owns the data source can use them.',
      'TrustTable does not apply them to later files or to other datasets, and it does not change your data. Rules cannot be created or edited here.',
    ],
  },
]

/** The Help screen. Static and read-only: it needs no analysis and makes no
 * request. */
export function HelpRoute() {
  return (
    <AppShell>
      <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
        Help
      </h1>
      <p className={BODY}>
        What the words in TrustTable mean, and where each result comes from.
      </p>
      <nav aria-label="Help topics" className="mt-4">
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {TOPICS.map((topic) => (
            <li key={topic.id}>
              <a
                href={`#${topic.id}`}
                className="font-medium text-slate-900 underline dark:text-slate-100"
              >
                {topic.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <div className="mt-6 flex flex-col gap-8">
        {TOPICS.map((topic) => (
          <section
            key={topic.id}
            id={topic.id}
            aria-labelledby={`${topic.id}-heading`}
          >
            <h2 id={`${topic.id}-heading`} className={HEADING}>
              {topic.title}
            </h2>
            {topic.body.map((paragraph) => (
              <p key={paragraph} className={BODY}>
                {paragraph}
              </p>
            ))}
          </section>
        ))}
      </div>
    </AppShell>
  )
}
