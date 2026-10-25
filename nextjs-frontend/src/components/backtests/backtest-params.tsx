import { formatUtc } from '@/components/analyses/format';
import type { BacktestOut } from '@/lib/api/backtests';
import { NO_VALUE, formatDuration, formatNumber } from '@/lib/backtests/format';

/** How a run was set up, so two runs can be compared. Symbols are shown as escaped text. */

type Param = { label: string; value: string };

export function runParams(run: BacktestOut): Param[] {
  const rules = run.rules;
  return [
    { label: 'Source', value: run.source },
    { label: 'Timeframe', value: run.tf },
    { label: 'Bars', value: String(run.bars) },
    { label: 'Symbols', value: run.symbols.length > 0 ? run.symbols.join(', ') : 'Watchlist' },
    { label: 'Reward to risk', value: rules ? String(rules.rr) : NO_VALUE },
    { label: 'Stop buffer (ATR)', value: rules ? String(rules.stop_buffer_atr) : NO_VALUE },
    { label: 'Time stop (bars)', value: rules ? String(rules.time_stop_bars) : NO_VALUE },
    { label: 'Spread', value: rules ? String(rules.spread) : NO_VALUE },
    { label: 'Min risk (ATR)', value: rules ? String(rules.min_risk_atr) : NO_VALUE },
    { label: 'Split', value: run.split === 'symbols' ? 'By symbol' : 'By time' },
    { label: 'Train fraction', value: formatNumber(run.train_fraction, 2) },
    { label: 'Seed', value: String(run.seed) },
    { label: 'Stride', value: String(run.stride) },
    { label: 'Started', value: formatUtc(run.created_at) },
    { label: 'Duration', value: formatDuration(run.duration_seconds) },
  ];
}

export function BacktestParams({ run }: { run: BacktestOut }) {
  return (
    <section aria-labelledby="backtest-params-heading" className="space-y-3">
      <h3 id="backtest-params-heading" className="text-lg font-semibold">
        Run parameters
      </h3>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-3">
        {runParams(run).map((param) => (
          <div key={param.label} className="flex justify-between gap-3 border-b py-1">
            <dt className="text-muted-foreground">{param.label}</dt>
            <dd className="break-all text-right font-medium tabular-nums">{param.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
