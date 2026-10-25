import type {
  BacktestListItem,
  BacktestOut,
  BacktestStatsOut,
  BacktestSummaryOut,
} from '@/lib/api/generated';

/** Backtest API bodies shaped like TRAD-46's responses. */

export function makeStats(overrides: Partial<BacktestStatsOut> = {}): BacktestStatsOut {
  return {
    n: 42,
    n_open: 1,
    n_void: 2,
    low_sample: false,
    hit_rate: 0.476,
    average_r: 0.31,
    expectancy_r: 0.31,
    median_r: -1,
    best_r: 2,
    worst_r: -1,
    total_r: 13.02,
    profit_factor: 1.59,
    max_drawdown_r: 4.5,
    avg_bars_held: 12.34,
    ci_low: 0.05,
    ci_high: 0.58,
    ...overrides,
  };
}

export function makeBacktest(overrides: Partial<BacktestOut> = {}): BacktestOut {
  return {
    id: 7,
    created_at: '2026-10-20T08:30:00Z',
    strategy: 'my-one',
    source: 'demo',
    tf: '1h',
    bars: 500,
    symbols: ['EURUSD', 'XAUUSD'],
    rules: { rr: 2, stop_buffer_atr: 0, time_stop_bars: 50, spread: 0, min_risk_atr: 0.1 },
    split: 'time',
    train_fraction: 0.6,
    seed: 0,
    stride: 1,
    status: 'done',
    verdict: 'pass',
    duration_seconds: 185,
    error: null,
    results: {
      pooled: null,
      in_sample: makeStats({ n: 60, expectancy_r: 0.4, total_r: 24 }),
      out_of_sample: makeStats(),
      baselines: {
        random: makeStats({ n: 40, expectancy_r: -0.05, ci_low: -0.3, ci_high: 0.2 }),
        flipped: makeStats({ n: 41, expectancy_r: -0.2, profit_factor: null }),
      },
    },
    ...overrides,
  };
}

export function makeListItem(overrides: Partial<BacktestListItem> = {}): BacktestListItem {
  return {
    id: 7,
    strategy: 'my-one',
    created_at: '2026-10-20T08:30:00Z',
    verdict: 'pass',
    n: 42,
    expectancy_r: 0.31,
    ci_low: 0.05,
    ci_high: 0.58,
    low_sample: false,
    status: 'done',
    source: 'demo',
    tf: '1h',
    bars: 500,
    duration_seconds: 185,
    error: null,
    ...overrides,
  };
}

export function makeSummary(overrides: Partial<BacktestSummaryOut> = {}): BacktestSummaryOut {
  return {
    id: 7,
    strategy: 'my-one',
    created_at: '2026-10-20T08:30:00Z',
    verdict: 'pass',
    n: 42,
    expectancy_r: 0.31,
    ci_low: 0.05,
    ci_high: 0.58,
    low_sample: false,
    ...overrides,
  };
}
