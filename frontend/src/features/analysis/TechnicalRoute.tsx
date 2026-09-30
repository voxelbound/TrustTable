import { useState } from 'react'
import { useParams } from 'react-router'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import type {
  AnalysisProfileResponse,
  AnalysisResource,
  ColumnProfileResponse,
  FindingItem,
} from '../../api'
import {
  useAnalysisFindings,
  useAnalysisProfile,
  useAnalysisResource,
} from './api'

const HEADING = 'text-xl font-semibold text-slate-900 dark:text-slate-100'
const MUTED = 'text-sm text-slate-600 dark:text-slate-400'
const TEXT = 'text-sm text-slate-900 dark:text-slate-100'

/** Renders any API-provided metric value as plain text. React escapes the
 * result, so dataset-derived strings can never become markup. */
function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (
    typeof value === 'number' ||
    typeof value === 'boolean' ||
    typeof value === 'bigint'
  ) {
    return String(value)
  }
  return JSON.stringify(value)
}

function MetricList({ metrics }: { metrics: Record<string, unknown> }) {
  const entries = Object.entries(metrics)
  if (entries.length === 0) {
    return <p className={MUTED}>No metrics were recorded.</p>
  }
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className={MUTED}>{key}</dt>
          <dd className={`${TEXT} break-all`}>{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="contents">
      <dt className={MUTED}>{label}</dt>
      <dd className={`${TEXT} break-all`}>{value}</dd>
    </div>
  )
}

function FactList({ children }: { children: React.ReactNode }) {
  return (
    <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
      {children}
    </dl>
  )
}

function describeScope(profile: AnalysisProfileResponse): string {
  const { scope, sample_size, population_size, method } = profile.sampling
  const full = sample_size === population_size
  if (full) {
    return `Full data: all ${population_size} rows were profiled (scope: ${scope}).`
  }
  const how = method ? `, method: ${method}` : ''
  return `Sampled: ${sample_size} of ${population_size} rows were profiled (scope: ${scope}${how}).`
}

interface DetectorRow {
  key: string
  detectorId: string
  version: string
  findings: number
  minConfidence: number
  maxConfidence: number
}

function summarizeDetectors(findings: FindingItem[]): DetectorRow[] {
  const rows = new Map<string, DetectorRow>()
  for (const finding of findings) {
    const key = `${finding.detector_id}@${finding.detector_version}`
    const row = rows.get(key)
    if (row) {
      row.findings += 1
      row.minConfidence = Math.min(row.minConfidence, finding.confidence)
      row.maxConfidence = Math.max(row.maxConfidence, finding.confidence)
    } else {
      rows.set(key, {
        key,
        detectorId: finding.detector_id,
        version: finding.detector_version,
        findings: 1,
        minConfidence: finding.confidence,
        maxConfidence: finding.confidence,
      })
    }
  }
  return [...rows.values()].sort((a, b) =>
    a.detectorId.localeCompare(b.detectorId),
  )
}

function ColumnRow({ column }: { column: ColumnProfileResponse }) {
  const [open, setOpen] = useState(false)
  const panelId = `column-metrics-${column.column.internal_key}`
  return (
    <li className="rounded border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className={`${TEXT} font-medium`}>{column.column.original_name}</p>
        <p className={MUTED}>
          {column.inferred_type} · {column.null_count} empty ·{' '}
          {column.distinct_count} distinct
        </p>
      </div>
      {column.warnings.length > 0 && (
        <ul className="mt-1 list-disc pl-5">
          {column.warnings.map((warning, index) => (
            <li key={`${warning.code}-${index}`} className={MUTED}>
              {warning.code}: {warning.message}
            </li>
          ))}
        </ul>
      )}
      <Button
        variant="secondary"
        className="mt-2"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`${open ? 'Hide' : 'Show'} metrics for ${column.column.original_name}`}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? 'Hide metrics' : 'Show metrics'}
      </Button>
      {open && (
        <div id={panelId} className="mt-2">
          <MetricList metrics={column.metrics} />
        </div>
      )}
    </li>
  )
}

function AnalysisSection({ analysis }: { analysis: AnalysisResource }) {
  const { dataset } = analysis
  return (
    <section aria-labelledby="technical-analysis-heading">
      <h2 id="technical-analysis-heading" className={HEADING}>
        Dataset and analysis
      </h2>
      <FactList>
        <Fact label="File name" value={dataset.original_filename} />
        <Fact label="Format" value={dataset.format} />
        <Fact label="Size (bytes)" value={String(dataset.byte_size)} />
        <Fact label="Content hash" value={dataset.content_hash} />
        <Fact label="Source" value={dataset.source_type} />
        <Fact label="Analysis state" value={analysis.state} />
        <Fact label="Created" value={analysis.created_at} />
        <Fact label="Started" value={formatValue(analysis.started_at)} />
        <Fact label="Completed" value={formatValue(analysis.completed_at)} />
      </FactList>
      <h3 className="mt-4 text-sm font-semibold text-slate-900 dark:text-slate-100">
        AI exposure
      </h3>
      <p className={`${MUTED} mt-1`}>
        Model provider enabled for detection:{' '}
        {analysis.security_exposure.model_provider_enabled ? 'yes' : 'no'}.
        Dataset samples sent to a model:{' '}
        {analysis.security_exposure.sample_transmission_enabled ? 'yes' : 'no'}.
        This describes the deterministic detection step only; AI explanations
        are requested separately per finding.
      </p>
    </section>
  )
}

function ProfileSection({ profile }: { profile: AnalysisProfileResponse }) {
  return (
    <section aria-labelledby="technical-profile-heading">
      <h2 id="technical-profile-heading" className={HEADING}>
        Profile
      </h2>
      <p className={`${TEXT} mt-2`}>{describeScope(profile)}</p>
      <FactList>
        <Fact label="Profile schema version" value={profile.schema_version} />
        <Fact
          label="Profiling duration (ms)"
          value={String(profile.timing.duration_ms)}
        />
        <Fact label="Profiling started" value={profile.timing.started_at} />
        <Fact label="Profiling completed" value={profile.timing.completed_at} />
      </FactList>

      <h3 className="mt-4 text-sm font-semibold text-slate-900 dark:text-slate-100">
        Dataset metrics
      </h3>
      <div className="mt-1">
        <MetricList metrics={profile.dataset_metrics} />
      </div>

      <h3 className="mt-4 text-sm font-semibold text-slate-900 dark:text-slate-100">
        Profiling warnings
      </h3>
      {profile.warnings.length === 0 ? (
        <p className={`${MUTED} mt-1`}>No profiling warnings.</p>
      ) : (
        <ul className="mt-1 list-disc pl-5">
          {profile.warnings.map((warning, index) => (
            <li key={`${warning.code}-${index}`} className={MUTED}>
              {warning.code}: {warning.message}
            </li>
          ))}
        </ul>
      )}

      <h3 className="mt-4 text-sm font-semibold text-slate-900 dark:text-slate-100">
        Columns ({profile.column_profiles.length})
      </h3>
      <ul className="mt-2 flex flex-col gap-3">
        {profile.column_profiles.map((column) => (
          <ColumnRow key={column.column.internal_key} column={column} />
        ))}
      </ul>
    </section>
  )
}

/** The Technical details screen (`docs/ui-specification.md` §4.11;
 * `UI-03` slice 5). Read-only: every value comes from an existing route
 * (`GET .../`, `.../profile`, `.../findings`). Information no route
 * exposes (detector thresholds, analysis-level prompt/model metadata) is
 * stated as not available rather than inferred. */
export function TechnicalRoute() {
  const { analysisId } = useParams<{ analysisId: string }>()
  const resourceQuery = useAnalysisResource(analysisId)
  const profileQuery = useAnalysisProfile(analysisId)
  const findingsQuery = useAnalysisFindings(analysisId)

  const findings = findingsQuery.data?.items ?? []
  const totalFindings = findingsQuery.data?.total_items ?? 0
  const detectors = summarizeDetectors(findings)

  return (
    <div className="flex flex-col gap-8">
      {resourceQuery.isLoading ? (
        <p role="status" aria-live="polite" className={MUTED}>
          Loading technical details…
        </p>
      ) : resourceQuery.isError ? (
        <Alert variant="error" title="Could not load analysis details">
          {resourceQuery.error.message}
        </Alert>
      ) : resourceQuery.data ? (
        <AnalysisSection analysis={resourceQuery.data} />
      ) : null}

      {profileQuery.isLoading ? (
        <p role="status" aria-live="polite" className={MUTED}>
          Loading profile…
        </p>
      ) : profileQuery.isError ? (
        <Alert variant="error" title="Could not load the profile">
          {profileQuery.error.message}
        </Alert>
      ) : profileQuery.data ? (
        <ProfileSection profile={profileQuery.data} />
      ) : null}

      <section aria-labelledby="technical-detectors-heading">
        <h2 id="technical-detectors-heading" className={HEADING}>
          Detectors that produced findings
        </h2>
        {findingsQuery.isLoading ? (
          <p role="status" aria-live="polite" className={`${MUTED} mt-2`}>
            Loading detectors…
          </p>
        ) : findingsQuery.isError ? (
          <div className="mt-2">
            <Alert variant="error" title="Could not load findings">
              {findingsQuery.error.message}
            </Alert>
          </div>
        ) : detectors.length === 0 ? (
          <p className={`${MUTED} mt-2`}>
            No detector produced a finding for this analysis.
          </p>
        ) : (
          <>
            {totalFindings > findings.length && (
              <p className={`${MUTED} mt-2`}>
                Based on the first {findings.length} of {totalFindings}{' '}
                findings.
              </p>
            )}
            <table className="mt-2 w-full text-left">
              <caption className="sr-only">Detectors and versions</caption>
              <thead>
                <tr className={MUTED}>
                  <th scope="col">Detector</th>
                  <th scope="col">Version</th>
                  <th scope="col">Findings</th>
                  <th scope="col">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {detectors.map((row) => (
                  <tr key={row.key} className={TEXT}>
                    <td className="break-all">{row.detectorId}</td>
                    <td>{row.version}</td>
                    <td>{row.findings}</td>
                    <td>
                      {row.minConfidence === row.maxConfidence
                        ? row.minConfidence
                        : `${row.minConfidence}–${row.maxConfidence}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        <p className={`${MUTED} mt-3`}>
          Detectors that found nothing are not listed. Detector thresholds and
          analysis-level prompt and model metadata are not available from the
          API yet.
        </p>
      </section>
    </div>
  )
}
