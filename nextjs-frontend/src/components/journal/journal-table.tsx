import { formatPrice, formatUtc } from '@/components/analyses/format';
import { StatusPill } from '@/components/ui/status-pill';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { JournalEntryOut } from '@/lib/api/journal';
import { NO_VALUE, formatR, rMultiple } from '@/lib/journal/format';

import { JournalRowActions } from './journal-row-actions';

/** The journal list. Symbols and notes are user text: rendered as plain, escaped text only. */
export function JournalTable({ entries }: { entries: JournalEntryOut[] }) {
  return (
    <Table stacked aria-label="Journal entries">
      <TableHeader>
        <TableRow>
          <TableHead>Trade</TableHead>
          <TableHead>Status</TableHead>
          <TableHead numeric>Entry</TableHead>
          <TableHead numeric>Stop</TableHead>
          <TableHead numeric>Exit</TableHead>
          <TableHead numeric>Result</TableHead>
          <TableHead>Opened</TableHead>
          <TableHead>Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((entry) => {
          const closed = entry.exit !== null && entry.exit !== undefined;
          return (
            <TableRow key={entry.id}>
              <TableCell label="Trade" className="font-medium">
                {entry.symbol} <span className="text-muted-foreground">{entry.timeframe}</span>{' '}
                <span className="text-muted-foreground">{entry.side}</span>
                {entry.notes ? (
                  <span className="block max-w-xs truncate text-xs font-normal text-muted-foreground">
                    {entry.notes}
                  </span>
                ) : null}
              </TableCell>
              <TableCell label="Status">
                {closed ? (
                  <StatusPill variant="neutral">Closed</StatusPill>
                ) : (
                  <StatusPill variant="info">Open</StatusPill>
                )}
              </TableCell>
              <TableCell label="Entry" numeric>
                {formatPrice(entry.entry)}
              </TableCell>
              <TableCell label="Stop" numeric>
                {formatPrice(entry.stop)}
              </TableCell>
              <TableCell label="Exit" numeric>
                {closed ? formatPrice(entry.exit) : NO_VALUE}
              </TableCell>
              <TableCell label="Result" numeric>
                {formatR(rMultiple(entry))}
              </TableCell>
              <TableCell label="Opened">{formatUtc(entry.opened_at)}</TableCell>
              <TableCell label="Actions">
                <JournalRowActions entry={entry} />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
