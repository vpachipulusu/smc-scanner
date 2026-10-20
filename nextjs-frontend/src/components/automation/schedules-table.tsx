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

import { ScheduleActions } from './schedule-actions';

/** The schedules list. Names and symbols are user text: rendered as plain, escaped text only. */
export function SchedulesTable({ schedules }: { schedules: ScheduleOut[] }) {
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
