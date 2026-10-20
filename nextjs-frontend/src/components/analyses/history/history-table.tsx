import Link from 'next/link';

import { ActionPill } from '@/components/common/action-pill';
import { ConfidenceBar } from '@/components/common/confidence-bar';
import { StatusPill } from '@/components/ui/status-pill';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { AnalysisOut } from '@/lib/api/analyses';
import { formatUtc, textOrNA } from '../format';

/** Past verdicts, newest first as the API returns them. React escapes every cell. */

function Verdict({ item }: { item: AnalysisOut }) {
  if (item.verdict) return <ActionPill action={item.verdict.action} />;
  return (
    <StatusPill variant={item.status === 'failed' ? 'warn' : 'neutral'}>
      {item.status === 'failed' ? 'Analysis failed' : 'No verdict'}
    </StatusPill>
  );
}

export function HistoryTable({ items }: { items: ReadonlyArray<AnalysisOut> }) {
  return (
    <Table stacked>
      <TableCaption>Stored AI verdicts, newest first</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Time</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead>TF</TableHead>
          <TableHead>Action</TableHead>
          <TableHead>Confidence</TableHead>
          <TableHead>Quality</TableHead>
          <TableHead>Zone</TableHead>
          <TableHead>Provider</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <TableRow key={item.id} data-testid="history-row">
            <TableCell label="Time" className="whitespace-nowrap">
              <Link
                href={`/analyses/${item.id}`}
                className="inline-block rounded-sm py-1 underline underline-offset-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <time dateTime={item.created_at}>{formatUtc(item.created_at)}</time>
                <span className="sr-only">{` — view ${item.symbol} ${item.tf} analysis`}</span>
              </Link>
            </TableCell>
            <TableCell label="Symbol" className="font-medium">
              {item.symbol}
            </TableCell>
            <TableCell label="TF">{item.tf}</TableCell>
            <TableCell label="Action">
              <Verdict item={item} />
            </TableCell>
            <TableCell label="Confidence">
              {item.verdict ? <ConfidenceBar value={item.verdict.confidence} /> : <NoValue />}
            </TableCell>
            <TableCell label="Quality">{item.verdict?.quality ?? <NoValue />}</TableCell>
            <TableCell label="Zone">{textOrNA(item.zone)}</TableCell>
            <TableCell label="Provider">{textOrNA(item.provider)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** An empty cell that is still announced, so a missing value reads as "none", not broken. */
function NoValue() {
  return (
    <span className="text-muted-foreground">
      <span aria-hidden="true">—</span>
      <span className="sr-only">Not available</span>
    </span>
  );
}
