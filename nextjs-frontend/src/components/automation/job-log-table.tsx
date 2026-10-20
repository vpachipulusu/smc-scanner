import { StatusPill } from '@/components/ui/status-pill';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { JobLogOut } from '@/lib/api/schedules';
import {
  LOG_STATUS_VIEWS,
  formatDateTime,
  formatDuration,
  summarizeError,
} from '@/lib/automation/format';

/**
 * Job-log rows. `skip_reason` and `error` are raw backend text: they are rendered only as React
 * text children (escaped), and the error is cut to its first line so no stack trace shows.
 */
export function JobLogTable({ logs }: { logs: JobLogOut[] }) {
  return (
    <Table stacked aria-label="Job log">
      <TableHeader>
        <TableRow>
          <TableHead>Started</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Duration</TableHead>
          <TableHead>Hits</TableHead>
          <TableHead>Delivered</TableHead>
          <TableHead>Details</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {logs.map((log) => {
          const view = LOG_STATUS_VIEWS[log.status];
          const error = summarizeError(log.error);
          const skipReason = summarizeError(log.skip_reason);
          return (
            <TableRow key={log.id}>
              <TableCell label="Started">{formatDateTime(log.started_at)}</TableCell>
              <TableCell label="Status">
                <StatusPill variant={view.variant}>{view.label}</StatusPill>
              </TableCell>
              <TableCell label="Duration">{formatDuration(log.duration_ms)}</TableCell>
              <TableCell label="Hits" numeric>
                {log.hits}
              </TableCell>
              <TableCell label="Delivered" numeric>
                {log.delivered}
              </TableCell>
              <TableCell label="Details" className="max-w-md break-words">
                {skipReason && <p>Skipped: {skipReason}</p>}
                {error && <p className="text-crit-foreground">Error: {error}</p>}
                {!skipReason && !error && '—'}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
