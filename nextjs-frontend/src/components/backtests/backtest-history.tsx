import Link from 'next/link';
import { Loader, TriangleAlert } from 'lucide-react';

import { formatUtc } from '@/components/analyses/format';
import { VerdictBadge } from '@/components/backtests/verdict-badge';
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
import type { BacktestListItem } from '@/lib/api/backtests';
import { NO_VALUE, formatDuration, formatInterval, formatRValue } from '@/lib/backtests/format';
import { backtestHref } from '@/lib/backtests/routes';
import { verdictKey } from '@/lib/backtests/verdict';

/** Previous runs of one strategy, newest first; each links to its own results. */

function RunStatus({ item }: { item: BacktestListItem }) {
  switch (item.status) {
    case 'done':
      return <VerdictBadge verdict={verdictKey(item.verdict)} />;
    case 'failed':
      return (
        <StatusPill variant="crit" icon={TriangleAlert}>
          Run failed
        </StatusPill>
      );
    default:
      return (
        <StatusPill variant="info" icon={Loader}>
          {item.status === 'pending' ? 'Pending' : 'Running'}
        </StatusPill>
      );
  }
}

type BacktestHistoryProps = {
  slug: string;
  items: readonly BacktestListItem[];
  selectedId: number | null;
};

export function BacktestHistory({ slug, items, selectedId }: BacktestHistoryProps) {
  return (
    <section aria-labelledby="backtest-history-heading" className="space-y-3">
      <h2 id="backtest-history-heading" className="text-xl font-semibold">
        History
      </h2>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="no-backtests">
          No runs yet.
        </p>
      ) : (
        <Table stacked>
          <TableCaption>Out-of-sample figures of each run, newest first.</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Started</TableHead>
              <TableHead scope="col">Result</TableHead>
              <TableHead scope="col">Data</TableHead>
              <TableHead scope="col" numeric>
                Closed trades
              </TableHead>
              <TableHead scope="col" numeric>
                Expectancy (95% interval)
              </TableHead>
              <TableHead scope="col" numeric>
                Duration
              </TableHead>
              <TableHead scope="col">
                <span className="sr-only">Open</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => {
              const selected = item.id === selectedId;
              return (
                <TableRow
                  key={item.id}
                  data-run={item.id}
                  className={selected ? 'bg-muted/60' : undefined}
                >
                  <TableCell label="Started">{formatUtc(item.created_at)}</TableCell>
                  <TableCell label="Result">
                    <RunStatus item={item} />
                  </TableCell>
                  <TableCell label="Data">{`${item.source} ${item.tf}, ${item.bars} bars`}</TableCell>
                  <TableCell numeric label="Closed trades">
                    {item.n ?? NO_VALUE}
                  </TableCell>
                  <TableCell numeric label="Expectancy">
                    {`${formatRValue(item.expectancy_r)} (${formatInterval(item.ci_low, item.ci_high)})`}
                  </TableCell>
                  <TableCell numeric label="Duration">
                    {formatDuration(item.duration_seconds)}
                  </TableCell>
                  <TableCell>
                    {selected ? (
                      <span className="text-xs text-muted-foreground" aria-current="true">
                        Shown above
                      </span>
                    ) : (
                      <Link
                        href={backtestHref(slug, item.id)}
                        className="text-sm underline underline-offset-4"
                        aria-label={`Open run of ${formatUtc(item.created_at)}`}
                      >
                        Open
                      </Link>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </section>
  );
}
