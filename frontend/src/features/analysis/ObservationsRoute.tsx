import { useParams } from 'react-router'
import { SectionIntro } from '../../components/ui/SectionIntro'
import { ObservationsList } from './ObservationsList'

/** The Observations screen (`UX-07`, D-075; `docs/ui-specification.md` §12.2).
 * The same read-only list the Overview shows under *Worth knowing*, with its
 * own place under Review. An observation is a pattern, not a finding. */
export function ObservationsRoute() {
  const { analysisId } = useParams<{ analysisId: string }>()
  return (
    <div className="flex flex-col gap-8">
      <SectionIntro
        title="Observations"
        group="Review"
        purpose="Patterns TrustTable saw in the data that are worth knowing. They are not findings: they have no severity, do not change the trust assessment and do not say that anything is wrong."
        availability="Once the analysis has completed. An analysis with nothing to note simply lists none."
        why="A pattern in the data can help explain a result, or be worth a question to whoever owns the data."
        next="Read an observation, and where it lists example rows open them in the inspector. Findings, which do affect the trust assessment, are under Findings."
      />
      <ObservationsList analysisId={analysisId} />
    </div>
  )
}
