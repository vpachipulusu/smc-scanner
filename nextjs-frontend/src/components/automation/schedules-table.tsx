import { StatusPill } from '@/components/ui/status-pill';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { ScheduleOut } from '@/lib/api/schedules';
import { formatDateTime } from '@/lib/automation/format';
import { DEFAULT_STRATEGY } from '@/lib/scan/params';
import { isMissingStrategy } from '@/lib/scan/strategy-options';

import { ScheduleActions } from './schedule-actions';

export const STRATEGY_MISSING_PILL = `Strategy missing: runs use ${DEFAULT_STRATEGY}`;

function StrategyLine({ slug, known }: { slug: string; known: ReadonlySet<string> | null }) {
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
      <span>
        Strategy: <span className="font-mono">{slug}</span>
      </span>
      {isMissingStrategy(known, slug) && (
        <StatusPill variant="warn">{STRATEGY_MISSING_PILL}</StatusPill>
      )}
    </span>
  );
}

/**
 * The schedules list. Names and symbols are user text: rendered as plain, escaped text only.
 * `knownStrategies` is the slug set from GET /strategies; when given, a schedule whose strategy
 * was deleted is flagged (its runs fall back to the default strategy).
 */
export function SchedulesTable({
  schedules,
  knownStrategies = null,
}: {
  schedules: ScheduleOut[];
  knownStrategies?: ReadonlySet<string> | null;
}) {
  return (
    <Table stacked aria-label="Schedules">
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Scan</TableHead>
          <TableHead>Last run</TableHead>
          <TableHead>Next run</TableHead>
          <TableHead>Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {schedules.map((schedule) => (
          <TableRow key={schedule.id}>
            <TableCell label="Name" className="font-medium">
              {schedule.name}
            </TableCell>
            <TableCell label="Status">
              {schedule.enabled ? (
                <StatusPill variant="good">Enabled</StatusPill>
              ) : (
                <StatusPill variant="neutral">Disabled</StatusPill>
              )}
            </TableCell>
            <TableCell label="Scan">
              {schedule.source} {schedule.tf} · every {schedule.frequency} ·{' '}
              {schedule.symbols.join(', ')}
              <StrategyLine slug={schedule.strategy ?? DEFAULT_STRATEGY} known={knownStrategies} />
              {schedule.mtf && (
                <span className="mt-1 flex flex-wrap gap-1">
                  <StatusPill variant="info">Multi-timeframe</StatusPill>
                  {schedule.require_htf_aligned && (
                    <StatusPill variant="info">HTF aligned only</StatusPill>
                  )}
                </span>
              )}
            </TableCell>
            <TableCell label="Last run">{formatDateTime(schedule.last_run_at)}</TableCell>
            <TableCell label="Next run">
              {schedule.enabled ? formatDateTime(schedule.next_run_at) : '—'}
            </TableCell>
            <TableCell label="Actions">
              <ScheduleActions schedule={schedule} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
