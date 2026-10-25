import { VerdictBadge } from '@/components/backtests/verdict-badge';
import type { BacktestStatsOut } from '@/lib/api/backtests';
import {
  formatDrawdown,
  formatInterval,
  formatNumber,
  formatPercent,
  formatProfitFactor,
  formatRValue,
} from '@/lib/backtests/format';
import { VERDICT_DESCRIPTIONS, type VerdictKey } from '@/lib/backtests/verdict';

/**
 * The headline figures of one run: its verdict and the out-of-sample statistics the verdict is
 * judged on (the pooled ones for a CLI run without a split), as a definition list of cards.
 */

type SummaryCard = { label: string; value: string; detail?: string };

function summaryCards(stats: BacktestStatsOut): SummaryCard[] {
  return [
    {
      label: 'Closed trades',
      value: String(stats.n),
      detail: `${stats.n_open} open, ${stats.n_void} void`,
    },
    { label: 'Hit rate', value: formatPercent(stats.hit_rate) },
    {
      label: 'Expectancy',
      value: formatRValue(stats.expectancy_r),
      detail: `95% interval ${formatInterval(stats.ci_low, stats.ci_high)}`,
    },
    { label: 'Profit factor', value: formatProfitFactor(stats.profit_factor, stats.n) },
    { label: 'Max drawdown', value: formatDrawdown(stats.max_drawdown_r) },
    { label: 'Avg bars held', value: formatNumber(stats.avg_bars_held) },
  ];
}

type BacktestSummaryProps = {
  verdict: VerdictKey;
  stats: BacktestStatsOut | null;
  /** Which part of the run `stats` is, e.g. "Out of sample". */
  scope: string;
};

export function BacktestSummary({ verdict, stats, scope }: BacktestSummaryProps) {
  return (
    <section aria-labelledby="backtest-summary-heading" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="backtest-summary-heading" className="text-lg font-semibold">
          Verdict
        </h3>
        <VerdictBadge verdict={verdict} />
      </div>
      <p className="text-sm text-muted-foreground" data-testid="verdict-description">
        {VERDICT_DESCRIPTIONS[verdict]}
      </p>
      {stats === null ? (
        <p className="text-sm text-muted-foreground">
          This run has no readable statistics to show.
        </p>
      ) : (
        <>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {scope}
          </h4>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {summaryCards(stats).map((card) => (
              <div key={card.label} className="rounded-lg border bg-card p-3">
                <dt className="text-xs text-muted-foreground">{card.label}</dt>
                <dd className="text-lg font-semibold tabular-nums">{card.value}</dd>
                {card.detail && (
                  <dd className="text-xs tabular-nums text-muted-foreground">{card.detail}</dd>
                )}
              </div>
            ))}
          </dl>
        </>
      )}
    </section>
  );
}
