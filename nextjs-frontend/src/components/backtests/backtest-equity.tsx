import { useId } from 'react';

import type { BacktestStatsOut } from '@/lib/api/backtests';
import { tradeCurve } from '@/lib/backtests/equity';
import { formatDrawdown, formatRValue } from '@/lib/backtests/format';

const BOX = { width: 640, height: 220, padding: 16 };

/** Shown instead of a curve: the API stores statistics only, not each trade. */
export const CURVE_NEEDS_EXPORT_MESSAGE =
  'The equity curve needs per-trade results, which the API does not store. Export them with the CLI (smc-backtest --out DIR) to draw it.';

type BacktestEquityProps = {
  /** Each closed trade's R in order, or null when the run has no per-trade data. */
  trades: readonly number[] | null;
  /** The out-of-sample figures shown when there is no curve. */
  stats: BacktestStatsOut | null;
};

/**
 * Cumulative R after each closed trade, drawn only from per-trade data. Without it the section
 * says how to get it and repeats the out-of-sample totals. The SVG has a title and a summary for
 * screen readers.
 */
export function BacktestEquity({ trades, stats }: BacktestEquityProps) {
  const titleId = useId();
  const descId = useId();
  const geometry = trades && trades.length > 0 ? tradeCurve(trades, BOX) : null;

  return (
    <section aria-labelledby="backtest-equity-heading" className="space-y-3">
      <h3 id="backtest-equity-heading" className="text-lg font-semibold">
        Equity curve (R)
      </h3>
      {geometry === null || geometry.points.length === 0 ? (
        <div className="space-y-1 rounded-lg border p-3 text-sm" data-testid="curve-unavailable">
          <p>{CURVE_NEEDS_EXPORT_MESSAGE}</p>
          {stats && (
            <p className="text-muted-foreground">
              {`Out of sample: total ${formatRValue(stats.total_r)} over ${stats.n} closed trades, max drawdown ${formatDrawdown(stats.max_drawdown_r)}.`}
            </p>
          )}
        </div>
      ) : (
        <figure className="space-y-2">
          <svg
            viewBox={`0 0 ${BOX.width} ${BOX.height}`}
            role="img"
            aria-labelledby={`${titleId} ${descId}`}
            className="h-auto w-full text-primary"
          >
            <title id={titleId}>Backtest equity curve</title>
            <desc id={descId}>
              {`Cumulative R over ${geometry.points.length} closed trades, ending at ${formatRValue(geometry.points[geometry.points.length - 1].point.cumulative_r)}.`}
            </desc>
            <line
              x1={BOX.padding}
              x2={BOX.width - BOX.padding}
              y1={geometry.baselineY}
              y2={geometry.baselineY}
              className="stroke-border"
              strokeDasharray="4 4"
            />
            <path
              d={geometry.path}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          </svg>
          <figcaption className="text-xs text-muted-foreground">
            Cumulative R after each closed trade; the dashed line is zero.
          </figcaption>
        </figure>
      )}
    </section>
  );
}
