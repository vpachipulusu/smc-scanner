import { describe, expect, it } from 'vitest';
import {
  NOT_AVAILABLE,
  formatPrice,
  formatUtc,
  parseAnalysisId,
} from '@/components/analyses/format';

describe('parseAnalysisId', () => {
  it.each([
    ['1', 1],
    ['42', 42],
  ])('accepts %s', (raw, expected) => {
    expect(parseAnalysisId(raw)).toBe(expected);
  });

  it.each(['0', '-1', '1.5', '1e3', 'abc', '', ' 7', '0x10', '007', '99999999999999999999'])(
    'rejects %j',
    (raw) => {
      expect(parseAnalysisId(raw)).toBeNull();
    }
  );
});

describe('formatPrice', () => {
  it.each([
    [2345.678, '2345.68'],
    [150.1234, '150.123'],
    [1.09898, '1.09898'],
    [0.012345678, '0.012346'],
  ])('formats %d by magnitude', (value, text) => {
    expect(formatPrice(value)).toBe(text);
  });

  it.each([null, undefined, Number.NaN, Number.POSITIVE_INFINITY])('shows N/A for %s', (value) => {
    expect(formatPrice(value)).toBe(NOT_AVAILABLE);
  });
});

describe('formatUtc', () => {
  it('formats an ISO time as UTC', () => {
    expect(formatUtc('2026-10-19T23:05:00Z')).toBe('2026-10-19 23:05 UTC');
  });

  it('treats a zone-less backend time as UTC', () => {
    expect(formatUtc('2026-10-19 23:00:00')).toBe('2026-10-19 23:00 UTC');
  });

  it('falls back to the raw text, or N/A when empty', () => {
    expect(formatUtc('not a date')).toBe('not a date');
    expect(formatUtc(null)).toBe(NOT_AVAILABLE);
    expect(formatUtc('')).toBe(NOT_AVAILABLE);
  });
});
