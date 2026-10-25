import { BacktestComparison } from '@/components/backtests/backtest-comparison';
import { BacktestEquity } from '@/components/backtests/backtest-equity';
import { BacktestParams } from '@/components/backtests/backtest-params';
import { BacktestSummary } from '@/components/backtests/backtest-summary';
import { ErrorBanner } from '@/components/dashboard/error-banner';
import type { BacktestOut, BacktestStatsOut } from '@/lib/api/backtests';
import { backtestRunErrorMessage } from '@/lib/api/backtests-messages';
import { verdictKey } from '@/lib/backtests/verdict';

/**
 * One run's results. A finished run shows its verdict, the out-of-sample figures, the baselines,
 * the curve (when per-trade data exists) and its parameters; a failed run its fixed error; a run
 * in flight a note that the page updates when it ends.
 */

/** The figures the verdict is judged on: out of sample, or pooled for a CLI run without a split. */
export function headlineStats(run: BacktestOut): { stats: BacktestStatsOut | null; scope: string } {
  const outOfSample = run.results?.out_of_sample ?? null;
  if (outOfSample) return { stats: outOfSample, scope: 'Out of sample' };
  const pooled = run.results?.pooled ?? null;
  return { stats: pooled, scope: 'Pooled (whole run)' };
}

export function BacktestDetail({ run }: { run: BacktestOut }) {
  if (run.status === 'pending' || run.status === 'running') {
    return (
      <div className="space-y-6">
        <p className="rounded-lg border p-3 text-sm" data-testid="run-in-flight">
          {`This run is ${run.status}. Its results appear here when it finishes.`}
        </p>
        <BacktestParams run={run} />
      </div>
    );
  }
  if (run.status === 'failed') {
    return (
      <div className="space-y-6">
        <ErrorBanner message={backtestRunErrorMessage(run.error)} />
        <BacktestParams run={run} />
      </div>
    );
  }
  const { stats, scope } = headlineStats(run);
  return (
    <div className="space-y-8">
      <BacktestSummary verdict={verdictKey(run.verdict)} stats={stats} scope={scope} />
      {run.results && <BacktestComparison results={run.results} />}
      <BacktestEquity trades={null} stats={stats} />
      <BacktestParams run={run} />
    </div>
  );
}
