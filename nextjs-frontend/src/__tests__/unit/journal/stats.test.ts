import { describe, expect, it } from 'vitest';
import { formatPercent, formatRValue, isStats } from '@/lib/journal/stats';
import { NO_VALUE } from '@/lib/journal/format';
import { makeEmptyStats, makeStats } from '../../helpers/journal-stats-fixtures';

describe('isStats', () => {
  it('accepts a full response, including null ratios', () => {
    expect(isStats(makeStats())).toBe(true);
    expect(isStats(makeEmptyStats())).toBe(true);
  });

  it.each([
    ['null', null],
    ['a string', 'x'],
    ['no summary', { cumulative: [] }],
    ['no cumulative', { summary: makeStats().summary }],
    ['cumulative not an array', { summary: makeStats().summary, cumulative: {} }],
    ['summary null', { summary: null, cumulative: [] }],
  ])('rejects %s', (_name, body) => {
    expect(isStats(body)).toBe(false);
  });

  it('rejects a non-numeric count or ratio', () => {
    const base = makeStats();
    expect(isStats({ ...base, summary: { ...base.summary, closed_trades: '4' } })).toBe(false);
    expect(isStats({ ...base, summary: { ...base.summary, win_rate: 'high' } })).toBe(false);
    expect(isStats({ ...base, summary: { ...base.summary, total_r: null } })).toBe(false);
  });

  it('rejects a malformed point', () => {
    const base = makeStats();
    expect(isStats({ ...base, cumulative: [{ entry_id: 1 }] })).toBe(false);
    expect(isStats({ ...base, cumulative: [null] })).toBe(false);
    expect(
      isStats({ ...base, cumulative: [{ entry_id: 1, closed_at: 5, r: 1, cumulative_r: 1 }] })
    ).toBe(false);
  });
});

describe('formatPercent', () => {
  it('shows a ratio as a whole or one-decimal percentage', () => {
    expect(formatPercent(0.5)).toBe('50%');
    expect(formatPercent(0.6667)).toBe('66.7%');
    expect(formatPercent(0)).toBe('0%');
    expect(formatPercent(1)).toBe('100%');
  });

  it('shows the placeholder for null, undefined or a non-finite value', () => {
    expect(formatPercent(null)).toBe(NO_VALUE);
    expect(formatPercent(undefined)).toBe(NO_VALUE);
    expect(formatPercent(Number.NaN)).toBe(NO_VALUE);
    expect(formatPercent(Number.POSITIVE_INFINITY)).toBe(NO_VALUE);
  });
});

describe('formatRValue', () => {
  it('formats a finite number as R and anything else as the placeholder', () => {
    expect(formatRValue(2)).toBe('+2.00R');
    expect(formatRValue(-0.5)).toBe('-0.50R');
    expect(formatRValue(null)).toBe(NO_VALUE);
    expect(formatRValue(Number.NaN)).toBe(NO_VALUE);
  });
});
