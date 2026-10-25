/** Pure backtest helpers: messages, verdict mapping, formatting, routes and the equity points. */
import { describe, expect, it } from 'vitest';

import {
  BACKTEST_NOT_FOUND_MESSAGE,
  BACKTEST_RUN_FAILED_MESSAGE,
  BACKTESTS_RATE_LIMIT_FALLBACK_MESSAGE,
  BACKTESTS_REQUEST_FAILED_MESSAGE,
  BACKTESTS_UNAUTHORIZED_MESSAGE,
  BACKTESTS_UNAVAILABLE_MESSAGE,
  backtestErrorMessage,
  backtestRateLimitMessage,
  backtestRunErrorMessage,
  validRetryAfter,
} from '@/lib/api/backtests-messages';
import { cumulativeTrades, tradeCurve } from '@/lib/backtests/equity';
import {
  NO_VALUE,
  formatCost,
  formatDrawdown,
  formatDuration,
  formatInterval,
  formatNumber,
  formatProfitFactor,
} from '@/lib/backtests/format';
import { backtestHref, parseRunId } from '@/lib/backtests/routes';
import { isFinished } from '@/lib/backtests/state';
import {
  VERDICT_DESCRIPTIONS,
  VERDICT_LABELS,
  badgeVerdict,
  verdictFor,
  verdictKey,
} from '@/lib/backtests/verdict';

describe('backtest messages', () => {
  it('maps statuses to fixed messages', () => {
    expect(backtestErrorMessage({})).toBe(BACKTESTS_UNAVAILABLE_MESSAGE);
    expect(backtestErrorMessage({ status: 401 })).toBe(BACKTESTS_UNAUTHORIZED_MESSAGE);
    expect(backtestErrorMessage({ status: 404 })).toBe(BACKTEST_NOT_FOUND_MESSAGE);
    expect(backtestErrorMessage({ status: 500, reason: 'boom' })).toBe(
      BACKTESTS_REQUEST_FAILED_MESSAGE
    );
    expect(backtestErrorMessage({ status: 422, reason: 'toString' })).not.toContain('function');
  });

  it('words the 429 wait and falls back without a usable Retry-After', () => {
    expect(backtestRateLimitMessage(1)).toBe('Too many backtest requests. Try again in 1 second.');
    expect(backtestRateLimitMessage(90)).toContain('90 seconds');
    expect(backtestRateLimitMessage(0)).toBe(BACKTESTS_RATE_LIMIT_FALLBACK_MESSAGE);
    expect(backtestRateLimitMessage(1.5)).toBe(BACKTESTS_RATE_LIMIT_FALLBACK_MESSAGE);
    expect(backtestRateLimitMessage(10 ** 7)).toBe(BACKTESTS_RATE_LIMIT_FALLBACK_MESSAGE);
    expect(validRetryAfter(undefined)).toBeUndefined();
  });

  it('shows a failed run’s fixed error in our words, and nothing unknown', () => {
    expect(backtestRunErrorMessage('Backtest failed; see the server log')).toBe(
      BACKTEST_RUN_FAILED_MESSAGE
    );
    expect(backtestRunErrorMessage('No symbol could be loaded')).toMatch(/No symbol/);
    expect(backtestRunErrorMessage('Backtest interrupted by a server restart')).toMatch(/restart/);
    expect(backtestRunErrorMessage('<script>')).toBe(BACKTEST_RUN_FAILED_MESSAGE);
    expect(backtestRunErrorMessage(null)).toBe(BACKTEST_RUN_FAILED_MESSAGE);
  });
});

describe('verdict mapping', () => {
  it('maps the API verdicts to badge keys', () => {
    expect(verdictKey('pass')).toBe('survived');
    expect(verdictKey('fail')).toBe('failed');
    expect(verdictKey('insufficient')).toBe('insufficient');
    expect(verdictKey(null)).toBe('unknown');
    expect(badgeVerdict(null)).toBe('not-run');
    expect(badgeVerdict({ verdict: 'pass' })).toBe('survived');
  });

  it('labels each verdict in words and explains the 30-trade threshold', () => {
    expect(VERDICT_LABELS).toEqual({
      survived: 'Survived',
      failed: 'Failed',
      insufficient: 'Insufficient',
      'not-run': 'Not run',
      unknown: 'No verdict',
    });
    expect(VERDICT_DESCRIPTIONS.insufficient).toContain('Fewer than 30 closed');
  });

  it('reads own keys only', () => {
    expect(verdictFor({ a: 'failed' }, 'a')).toBe('failed');
    expect(verdictFor({}, 'constructor')).toBeUndefined();
  });
});

describe('backtest formatting', () => {
  it('formats figures and dashes the missing ones', () => {
    expect(formatInterval(-0.12, 0.4)).toBe('-0.12R to +0.40R');
    expect(formatInterval(null, 0.4)).toBe(NO_VALUE);
    expect(formatProfitFactor(1.587, 10)).toBe('1.59');
    expect(formatProfitFactor(null, 10)).toBe('No losses');
    expect(formatProfitFactor(null, 0)).toBe(NO_VALUE);
    expect(formatDrawdown(4.5)).toBe('−4.50R');
    expect(formatDrawdown(0)).toBe('0.00R');
    expect(formatDrawdown(null)).toBe(NO_VALUE);
    expect(formatNumber(12.345)).toBe('12.3');
    expect(formatNumber(Number.NaN)).toBe(NO_VALUE);
  });

  it('formats durations and costs', () => {
    expect(formatDuration(45)).toBe('45 s');
    expect(formatDuration(185)).toBe('3 min 05 s');
    expect(formatDuration(3720)).toBe('1 h 02 min');
    expect(formatDuration(-1)).toBe(NO_VALUE);
    expect(formatDuration(null)).toBe(NO_VALUE);
    expect(formatCost(1.2e8)).toBe('1.2e8');
    expect(formatCost(1e8)).toBe('1e8');
    expect(formatCost(500)).toBe('500');
    expect(formatCost(Number.POSITIVE_INFINITY)).toBe(NO_VALUE);
  });
});

describe('routes and state', () => {
  it('builds the page link and reads ?run=', () => {
    expect(backtestHref('my-one')).toBe('/strategies/my-one/backtest');
    expect(backtestHref('my-one', 4)).toBe('/strategies/my-one/backtest?run=4');
    expect(parseRunId('12')).toBe(12);
    expect(parseRunId('0')).toBeNull();
    expect(parseRunId('1e3')).toBeNull();
    expect(parseRunId(['1'])).toBeNull();
    expect(parseRunId(undefined)).toBeNull();
  });

  it('knows when a run has ended', () => {
    expect(isFinished('done')).toBe(true);
    expect(isFinished('failed')).toBe(true);
    expect(isFinished('running')).toBe(false);
  });
});

describe('equity curve points', () => {
  it('accumulates R in trade order and skips non-finite values', () => {
    expect(cumulativeTrades([2, -1, Number.NaN, -1, 2]).map((p) => p.cumulative_r)).toEqual([
      2, 1, 0, 2,
    ]);
    expect(cumulativeTrades([0.1, 0.2])[1].cumulative_r).toBe(0.3);
  });

  it('maps the points into the box with zero inside the range', () => {
    const geometry = tradeCurve([1, 1, -3], { width: 100, height: 100, padding: 10 });
    expect(geometry.points.map((p) => p.x)).toEqual([10, 50, 90]);
    expect(geometry.path.startsWith('M10 ')).toBe(true);
    expect(geometry.baselineY).toBeGreaterThan(10);
    expect(tradeCurve([], { width: 100, height: 100, padding: 10 }).points).toEqual([]);
  });
});
