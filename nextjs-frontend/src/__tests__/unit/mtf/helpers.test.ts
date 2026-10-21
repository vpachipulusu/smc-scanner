/** Timeframe neighbours and HTF alignment, derived the way the API derives them. */
import { describe, expect, it } from 'vitest';
import { htfAlignment, htfAlignmentLabel, higherTimeframe, scanTimeframes } from '@/lib/scan/mtf';

describe('scanTimeframes', () => {
  it('lists the scan timeframe, then its higher and lower neighbours', () => {
    expect(scanTimeframes('1h')).toEqual(['1h', '4h', '30m']);
  });

  it('drops the missing neighbour at either end', () => {
    expect(scanTimeframes('1d')).toEqual(['1d', '4h']);
    expect(scanTimeframes('5m')).toEqual(['5m', '15m']);
  });
});

describe('higherTimeframe', () => {
  it('returns the used timeframe above the scan timeframe', () => {
    expect(higherTimeframe('1h', ['1h', '4h', '30m'])).toBe('4h');
  });

  it('is null when nothing higher was used, e.g. on 1d', () => {
    expect(higherTimeframe('1d', ['1d', '4h'])).toBeNull();
    expect(higherTimeframe('1h', ['1h'])).toBeNull();
  });

  it('ignores unknown timeframe names and a non-list', () => {
    expect(higherTimeframe('1h', ['1h', '<b>9h</b>'])).toBeNull();
    expect(higherTimeframe('1h', undefined)).toBeNull();
    expect(higherTimeframe('weird', ['4h'])).toBeNull();
  });
});

describe('htfAlignment', () => {
  it.each([
    ['bull OB', 'bullish', 'aligned'],
    ['bear FVG', 'bearish', 'aligned'],
    ['bull OB', 'bearish', 'conflict'],
    ['bear FVG', 'bullish', 'conflict'],
    ['bull FVG', 'range', 'range'],
    ['bull FVG', null, 'n/a'],
    ['bull FVG', undefined, 'n/a'],
  ] as const)('%s with HTF %s is %s', (zone, bias, expected) => {
    expect(htfAlignment({ zone, htf_bias: bias })).toBe(expected);
  });

  it('is n/a for a zone label that is neither bull nor bear', () => {
    expect(htfAlignment({ zone: 'Weird', htf_bias: 'bullish' })).toBe('n/a');
  });

  it('treats an unexpected bias value as n/a rather than a conflict', () => {
    const odd = { zone: 'bull OB', htf_bias: 'sideways' } as unknown as Parameters<
      typeof htfAlignment
    >[0];
    expect(htfAlignment(odd)).toBe('n/a');
  });

  it('has a plain label for each state', () => {
    expect(htfAlignmentLabel('aligned')).toBe('Aligned');
    expect(htfAlignmentLabel('conflict')).toBe('Against HTF');
    expect(htfAlignmentLabel('range')).toBe('HTF range');
    expect(htfAlignmentLabel('n/a')).toBe('n/a');
  });
});
