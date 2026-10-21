import { Card } from '@/components/ui/card';
import {
  formatCount,
  formatPercent,
  formatRValue,
  type JournalStatsSummary,
} from '@/lib/journal/stats';

/** The headline numbers over closed trades, in R. Open trades are only counted. */
export function JournalStatsCards({ summary }: { summary: JournalStatsSummary }) {
  const hasClosed = summary.closed_trades > 0;
  const closedOnly = (text: string) => (hasClosed ? text : formatRValue(null));
  const items: ReadonlyArray<{ label: string; value: string }> = [
    { label: 'Closed trades', value: formatCount(summary.closed_trades) },
    { label: 'Open trades', value: formatCount(summary.open_trades) },
    { label: 'Win rate', value: closedOnly(formatPercent(summary.win_rate)) },
    { label: 'Average R', value: closedOnly(formatRValue(summary.average_r)) },
    { label: 'Expectancy', value: closedOnly(formatRValue(summary.expectancy)) },
    { label: 'Total R', value: closedOnly(formatRValue(summary.total_r)) },
    { label: 'Average win', value: closedOnly(formatRValue(summary.avg_win_r)) },
    { label: 'Average loss', value: closedOnly(formatRValue(summary.avg_loss_r)) },
    {
      label: 'Wins / losses / even',
      value: closedOnly(
        `${formatCount(summary.wins)} / ${formatCount(summary.losses)} / ${formatCount(summary.breakeven)}`
      ),
    },
  ];

  return (
    <section aria-label="Journal statistics" className="space-y-2">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {items.map((item) => (
          <Card key={item.label} className="space-y-1 p-4">
            <dt className="text-xs text-muted-foreground">{item.label}</dt>
            <dd className="text-xl font-semibold tabular-nums">{item.value}</dd>
          </Card>
        ))}
      </dl>
      {!hasClosed && (
        <p className="text-sm text-muted-foreground" data-testid="journal-stats-empty">
          No closed trades yet. Results appear once a trade has an exit price.
        </p>
      )}
    </section>
  );
}
