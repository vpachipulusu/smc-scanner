import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { BacktestResultsOut, BacktestStatsOut } from '@/lib/api/backtests';
import {
  formatDrawdown,
  formatInterval,
  formatNumber,
  formatPercent,
  formatProfitFactor,
  formatRValue,
} from '@/lib/backtests/format';

/**
 * In-sample against out-of-sample against the null baselines (random entries and flipped
 * direction, both on the out-of-sample part). A strategy survives only if its out-of-sample
 * expectancy beats both baselines.
 */

type Row = { key: string; label: string; stats: BacktestStatsOut };

/** The parts the run produced, in reading order; missing parts are left out. */
export function comparisonRows(results: BacktestResultsOut): Row[] {
  const parts: Array<[string, string, BacktestStatsOut | null | undefined]> = [
    ['in_sample', 'In sample', results.in_sample],
    ['out_of_sample', 'Out of sample', results.out_of_sample],
    ['random', 'Random baseline', results.baselines?.random],
    ['flipped', 'Flipped baseline', results.baselines?.flipped],
    ['pooled', 'Pooled (whole run)', results.pooled],
  ];
  return parts.flatMap(([key, label, stats]) => (stats ? [{ key, label, stats }] : []));
}

const COLUMNS = [
  'Closed trades',
  'Hit rate',
  'Expectancy',
  '95% interval',
  'Profit factor',
  'Max drawdown',
  'Avg bars held',
  'Total R',
] as const;

export function BacktestComparison({ results }: { results: BacktestResultsOut }) {
  const rows = comparisonRows(results);
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="backtest-comparison-heading" className="space-y-3">
      <h3 id="backtest-comparison-heading" className="text-lg font-semibold">
        Against the baselines
      </h3>
      <Table stacked>
        <TableCaption visible>
          Random entries and flipped direction are replayed on the out-of-sample part.
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">Part</TableHead>
            {COLUMNS.map((column) => (
              <TableHead key={column} scope="col" numeric>
                {column}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ key, label, stats }) => (
            <TableRow key={key} data-part={key}>
              <TableHead
                scope="row"
                role="rowheader"
                className="h-auto bg-transparent py-3 text-sm font-medium normal-case tracking-normal text-foreground"
              >
                {label}
              </TableHead>
              <TableCell numeric label={COLUMNS[0]}>
                {stats.n}
              </TableCell>
              <TableCell numeric label={COLUMNS[1]}>
                {formatPercent(stats.hit_rate)}
              </TableCell>
              <TableCell numeric label={COLUMNS[2]}>
                {formatRValue(stats.expectancy_r)}
              </TableCell>
              <TableCell numeric label={COLUMNS[3]}>
                {formatInterval(stats.ci_low, stats.ci_high)}
              </TableCell>
              <TableCell numeric label={COLUMNS[4]}>
                {formatProfitFactor(stats.profit_factor, stats.n)}
              </TableCell>
              <TableCell numeric label={COLUMNS[5]}>
                {formatDrawdown(stats.max_drawdown_r)}
              </TableCell>
              <TableCell numeric label={COLUMNS[6]}>
                {formatNumber(stats.avg_bars_held)}
              </TableCell>
              <TableCell numeric label={COLUMNS[7]}>
                {formatRValue(stats.total_r)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}
