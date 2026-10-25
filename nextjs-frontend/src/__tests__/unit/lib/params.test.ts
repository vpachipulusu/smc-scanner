/** Search params: lenient parsing with per-field defaults, and a href that round-trips. */
import { describe, expect, it } from 'vitest';
import {
  DEFAULTS,
  LIMITS,
  parseScanParams,
  parseSymbols,
  scanHref,
  scanSearchParams,
} from '@/lib/scan/params';

describe('parseScanParams', () => {
  it('uses the defaults for an empty query', () => {
    expect(parseScanParams({})).toEqual({ query: DEFAULTS, every: 0 });
  });

  it('reads every field', () => {
    const parsed = parseScanParams({
      source: 'demo',
      tf: '15m',
      symbols: 'EURUSD, XAUUSD',
      bars: '300',
      swing: '5',
      near: '0.4',
      all: '1',
      every: '15',
    });

    expect(parsed).toEqual({
      query: {
        source: 'demo',
        tf: '15m',
        symbols: ['EURUSD', 'XAUUSD'],
        bars: 300,
        swing: 5,
        near: 0.4,
        allTouches: true,
        mtf: false,
        requireHtfAligned: false,
        strategy: 'smc-default',
      },
      every: 15,
    });
  });

  it.each([
    ['source', 'csv', 'source', DEFAULTS.source],
    ['tf', '2h', 'tf', DEFAULTS.tf],
    ['bars', '1', 'bars', DEFAULTS.bars],
    ['bars', '9999999', 'bars', DEFAULTS.bars],
    ['bars', '12.5', 'bars', DEFAULTS.bars],
    ['swing', '0', 'swing', DEFAULTS.swing],
    ['near', 'nan', 'near', DEFAULTS.near],
    ['near', '', 'near', DEFAULTS.near],
    ['bars', '', 'bars', DEFAULTS.bars],
    ['near', '-1', 'near', DEFAULTS.near],
    ['near', '99', 'near', DEFAULTS.near],
  ])('falls back to the default for %s=%s', (key, value, field, expected) => {
    const { query } = parseScanParams({ [key]: value });
    expect(query[field as keyof typeof query]).toBe(expected);
  });

  it('turns an invalid rescan interval off', () => {
    expect(parseScanParams({ every: '-5' }).every).toBe(0);
    expect(parseScanParams({ every: 'soon' }).every).toBe(0);
    expect(parseScanParams({ every: String(LIMITS.maxEvery + 1) }).every).toBe(0);
  });

  it('takes the first value of a repeated param', () => {
    expect(parseScanParams({ tf: ['4h', '1d'] }).query.tf).toBe('4h');
  });

  it.each(['1', 'on', 'true', 'YES'])('treats all=%s as include touched zones', (value) => {
    expect(parseScanParams({ all: value }).query.allTouches).toBe(true);
  });

  it('treats other all values as off', () => {
    expect(parseScanParams({ all: '0' }).query.allTouches).toBe(false);
    expect(parseScanParams({ all: 'no' }).query.allTouches).toBe(false);
  });
});

describe('parseSymbols', () => {
  it('splits on commas and whitespace, drops bad names, dedupes', () => {
    expect(parseSymbols('eurusd, XAUUSD ../../x USTEC\nEURUSD eurusd')).toEqual([
      'eurusd',
      'XAUUSD',
      'USTEC',
      'EURUSD',
    ]);
  });

  it('caps the list', () => {
    const many = Array.from({ length: 60 }, (_, i) => `S${i}`).join(',');
    expect(parseSymbols(many)).toHaveLength(LIMITS.maxSymbols);
  });

  it('is empty for nothing', () => {
    expect(parseSymbols(undefined)).toEqual([]);
    expect(parseSymbols('  ,  ')).toEqual([]);
  });
});

describe('scanHref', () => {
  it('is the bare path for the defaults', () => {
    expect(scanHref({ query: DEFAULTS, every: 0 })).toBe('/scan');
  });

  it('round-trips every non-default field', () => {
    const params = {
      query: {
        source: 'demo' as const,
        tf: '4h' as const,
        symbols: ['EURUSD', 'XAUUSD'],
        bars: 250,
        swing: 7,
        near: 0.3,
        allTouches: true,
        mtf: true,
        requireHtfAligned: true,
        strategy: 'smc-default',
      },
      every: 30,
    };

    const raw = Object.fromEntries(scanSearchParams(params));

    expect(parseScanParams(raw)).toEqual(params);
    expect(scanHref(params)).toBe(
      '/scan?source=demo&tf=4h&symbols=EURUSD%2CXAUUSD&bars=250&swing=7&near=0.3&all=1&mtf=1&htf=1&every=30'
    );
  });

  it('builds the export link on another path', () => {
    expect(scanHref({ query: { ...DEFAULTS, tf: '5m' }, every: 0 }, '/scan/export')).toBe(
      '/scan/export?tf=5m'
    );
  });
});
