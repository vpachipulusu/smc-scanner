import { TriangleAlert } from 'lucide-react';

import { StatusPill } from '@/components/ui/status-pill';
import type { CalendarResponse } from '@/lib/api/calendar';
import { riskLabel, riskTone, statusLabel } from '@/lib/calendar/format';

type Props = {
  risk: CalendarResponse['immediate_risk'];
  status: CalendarResponse['calendar_status'];
};

/**
 * News risk as icon + text + tint. With no calendar data the risk is unknown, so the badge says
 * that instead of "no risk"; stale data keeps the risk and adds a stale pill.
 */
export function RiskBadge({ risk, status }: Props) {
  if (status === 'unavailable') {
    return (
      <StatusPill variant="neutral" icon={TriangleAlert}>
        {statusLabel(status)}: news risk unknown
      </StatusPill>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <StatusPill variant={riskTone(risk)}>{riskLabel(risk)}</StatusPill>
      {status === 'stale' && <StatusPill variant="warn">{statusLabel(status)}</StatusPill>}
    </span>
  );
}
