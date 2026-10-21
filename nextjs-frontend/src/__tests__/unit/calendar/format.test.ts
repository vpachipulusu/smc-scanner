import { describe, expect, it } from 'vitest';
import {
  MAX_TITLE_LENGTH,
  NO_VALUE,
  formatCurrency,
  formatFigure,
  formatTitle,
  impactLabel,
  impactTone,
  riskLabel,
  riskTone,
  statusLabel,
} from '@/lib/calendar/format';

describe('calendar format', () => {
  it('labels and tones every risk, status and impact', () => {
    expect(riskLabel('none')).toMatch(/no immediate/i);
    expect(riskLabel('elevated')).toMatch(/elevated/i);
    expect(riskLabel('high')).toMatch(/high/i);
    expect([riskTone('none'), riskTone('elevated'), riskTone('high')]).toEqual([
      'good',
      'warn',
      'crit',
    ]);
    expect(statusLabel('fresh')).toMatch(/up to date/i);
    expect(statusLabel('stale')).toMatch(/stale/i);
    expect(statusLabel('unavailable')).toMatch(/unavailable/i);
    expect(impactLabel('holiday')).toBe('Holiday');
    expect(impactLabel('low')).toBe('Low');
    expect(impactTone('high')).toBe('crit');
    expect(impactTone('medium')).toBe('warn');
    expect(impactTone('low')).toBe('neutral');
    expect(impactTone('holiday')).toBe('info');
  });

  it('formats figures and shows a placeholder for missing or non-finite numbers', () => {
    expect(formatFigure(175.5)).toBe('175.5');
    expect(formatFigure(0.1 + 0.2)).toBe('0.3');
    expect(formatFigure(0)).toBe('0');
    expect(formatFigure(null)).toBe(NO_VALUE);
    expect(formatFigure(undefined)).toBe(NO_VALUE);
    expect(formatFigure(NaN)).toBe(NO_VALUE);
    expect(formatFigure(Infinity)).toBe(NO_VALUE);
  });

  it('cleans, truncates and defaults titles', () => {
    expect(formatTitle('  CPI \n y/y\t')).toBe('CPI y/y');
    expect(formatTitle('a\u0000b\u009fc')).toBe('a b c');
    expect(formatTitle('   ')).toBe(NO_VALUE);
    expect(formatTitle('Low‮ CPI​')).toBe('Low CPI');
    expect(formatCurrency('U‮SD')).toBe('USD');
    const long = formatTitle('x'.repeat(500));
    expect(long.length).toBe(MAX_TITLE_LENGTH);
    expect(long.endsWith('…')).toBe(true);
    expect(formatTitle('<script>alert(1)</script>')).toBe('<script>alert(1)</script>');
  });

  it('cleans and truncates currencies', () => {
    expect(formatCurrency(' USD ')).toBe('USD');
    expect(formatCurrency('')).toBe(NO_VALUE);
    expect(formatCurrency('ABCDEFGHIJKL').length).toBe(8);
  });
});
