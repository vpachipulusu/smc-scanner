import { describe, expect, it } from 'vitest';
import {
  HISTORY_PAGE_SIZE,
  historyHref,
  parseHistoryParams,
} from '@/components/analyses/history/params';

describe('parseHistoryParams', () => {
  it('returns no filters for an empty URL', () => {
    expect(parseHistoryParams({})).toEqual({});
  });

  it('reads valid filters and the cursor', () => {
    expect(
      parseHistoryParams({ symbol: 'EURUSD', action: 'sell', min_conf: '60', cursor: 'aWQ6NDI=' })
    ).toEqual({ symbol: 'EURUSD', action: 'SELL', minConfidence: 60, cursor: 'aWQ6NDI=' });
  });

  it('drops values that fail the allow-list instead of failing', () => {
    expect(
      parseHistoryParams({
        symbol: '<script>',
        action: 'MOON',
        min_conf: 'abc',
        cursor: 'not a cursor!',
      })
    ).toEqual({});
  });

  it('drops out-of-range confidence and zero', () => {
    expect(parseHistoryParams({ min_conf: '101' })).toEqual({});
    expect(parseHistoryParams({ min_conf: '-5' })).toEqual({});
    expect(parseHistoryParams({ min_conf: '0' })).toEqual({});
    expect(parseHistoryParams({ min_conf: '55.5' })).toEqual({ minConfidence: 55.5 });
  });

  it('rejects exponent, hex and padded confidence values', () => {
    for (const value of ['1e2', '0x10', ' 5 ', '1e-7', '5.123']) {
      expect(parseHistoryParams({ min_conf: value })).toEqual({});
    }
  });

  it('uses the first of a repeated param and treats empty as absent', () => {
    expect(parseHistoryParams({ symbol: ['XAUUSD', 'EURUSD'], action: '' })).toEqual({
      symbol: 'XAUUSD',
    });
  });

  it('rejects a cursor longer than the API allows', () => {
    expect(parseHistoryParams({ cursor: 'a'.repeat(65) })).toEqual({});
  });
});

describe('historyHref', () => {
  it('is the bare path with no filters', () => {
    expect(historyHref({})).toBe('/analyses');
  });

  it('round-trips through the parser', () => {
    const params = {
      symbol: 'EURUSD',
      action: 'BUY',
      minConfidence: 70,
      cursor: 'aWQ6NDI=',
    } as const;
    const url = new URL(historyHref(params), 'http://localhost');
    expect(parseHistoryParams(Object.fromEntries(url.searchParams))).toEqual(params);
  });

  it('can swap the path and drop the cursor', () => {
    expect(historyHref({ symbol: 'EURUSD', cursor: 'aWQ6NDI=' }, '/analyses/export', false)).toBe(
      '/analyses/export?symbol=EURUSD'
    );
  });

  it('has a page size within the API limit', () => {
    expect(HISTORY_PAGE_SIZE).toBeGreaterThan(0);
    expect(HISTORY_PAGE_SIZE).toBeLessThanOrEqual(200);
  });
});
