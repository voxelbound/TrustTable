import { Badge, type BadgeTone } from '../ui/Badge'

/** `Severity` enum values (`domain/value_objects.py`, confirmed by
 * direct read 2026-08-30), each with a text label so severity is never
 * conveyed by color alone (`docs/ui-specification.md` §10). */
const SEVERITY_TEXT: Record<string, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  informational: 'Informational',
}

const SEVERITY_TONE: Record<string, BadgeTone> = {
  critical: 'danger',
  high: 'danger',
  medium: 'warning',
  low: 'info',
  informational: 'neutral',
}

export interface FindingSeverityBadgeProps {
  severity: string
}

/** Domain component (`docs/ui-specification.md` §5, "FindingSeverity"). */
export function FindingSeverityBadge({ severity }: FindingSeverityBadgeProps) {
  const text = SEVERITY_TEXT[severity] ?? severity
  const tone = SEVERITY_TONE[severity] ?? 'neutral'

  return <Badge tone={tone}>{text}</Badge>
}
