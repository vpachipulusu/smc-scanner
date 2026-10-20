/** Formatting helpers for the automation pages. */
import { describe, expect, it } from 'vitest';
import {
  formatDateTime,
  formatDuration,
  parseCursor,
  summarizeError,
} from '@/lib/automation/format';

describe('formatDateTime', () => {
  it('uses a fixed UTC format', () => {
    expect(formatDateTime('2026-10-20T14:03:59Z')).toBe('2026-10-20 14:03 UTC');
    expect(formatDateTime('2026-10-20T15:03:00+01:00')).toBe('2026-10-20 14:03 UTC');
  });

  it('shows a dash for missing or invalid times', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime('not a date')).toBe('—');
  });
});

describe('formatDuration', () => {
  it.each([
    [250, '250 ms'],
    [2300, '2.3 s'],
    [125_000, '2 min 5 s'],
    [-1, '—'],
    [Number.NaN, '—'],
  ])('formats %s', (ms, text) => {
    expect(formatDuration(ms)).toBe(text);
  });
});

describe('summarizeError', () => {
  it('keeps the first non-empty line only', () => {
    expect(summarizeError('\n  Boom  \nTraceback...')).toBe('Boom');
  });

  it('shortens a very long line', () => {
    const summary = summarizeError('x'.repeat(500));
    expect(summary).toHaveLength(201);
    expect(summary?.endsWith('…')).toBe(true);
  });

  it('returns null for nothing', () => {
    expect(summarizeError(null)).toBeNull();
    expect(summarizeError('')).toBeNull();
    expect(summarizeError('  \n ')).toBeNull();
  });
});

describe('parseCursor', () => {
  it('accepts a short string and rejects everything else', () => {
    expect(parseCursor('abc')).toBe('abc');
    expect(parseCursor('')).toBeUndefined();
    expect(parseCursor(undefined)).toBeUndefined();
    expect(parseCursor(['a', 'b'])).toBeUndefined();
    expect(parseCursor('x'.repeat(65))).toBeUndefined();
    expect(parseCursor('a/b?c')).toBeUndefined();
    expect(parseCursor('MjAyNi0xMC0yMA==')).toBe('MjAyNi0xMC0yMA==');
  });
});
