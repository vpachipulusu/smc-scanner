/** The run form is read from allow-listed fields and checked against the API's limits. */
import { describe, expect, it } from 'vitest';

import {
  BACKTEST_DEFAULTS,
  backtestCost,
  parseBacktestForm,
  readBacktestValues,
  splitSymbols,
} from '@/lib/backtests/form';

const formOf = (overrides: Record<string, string> = {}): FormData => {
  const form = new FormData();
  for (const [name, value] of Object.entries({ ...BACKTEST_DEFAULTS, ...overrides })) {
    form.set(name, value);
  }
  return form;
};

describe('parseBacktestForm', () => {
  it('builds the API body from the defaults, leaving symbols out for the watchlist', () => {
    const parsed = parseBacktestForm(formOf());
    expect(parsed).toEqual({
      ok: true,
      values: BACKTEST_DEFAULTS,
      body: {
        source: 'demo',
        tf: '1h',
        bars: 500,
        rules: { rr: 2, stop_buffer_atr: 0, time_stop_bars: 50, spread: 0, min_risk_atr: 0.1 },
        split: 'time',
        train_fraction: 0.6,
        seed: 0,
        stride: 1,
      },
    });
  });

  it('sends deduplicated symbols', () => {
    const parsed = parseBacktestForm(
      formOf({ symbols: 'EURUSD, XAUUSD EURUSD', split: 'symbols' })
    );
    expect(parsed.ok && parsed.body.symbols).toEqual(['EURUSD', 'XAUUSD']);
  });

  it.each([
    ['bars', '14', /from 15 to 5000/],
    ['bars', '500.5', /whole number/],
    ['bars', '', /Enter a number/],
    ['rr', '0', /above 0/],
    ['train_fraction', '0.95', /0.3 to 0.9/],
    ['stride', '101', /1 to 100/],
    ['seed', 'abc', /Enter a number/],
    ['bars', '1e3', /Enter a number/],
    ['stride', '0x10', /Enter a number/],
    ['time_stop_bars', '0', /1 to 5000/],
    ['source', 'csv', /demo or MT5/],
    ['tf', '2h', /timeframe/],
    ['split', 'random', /split/],
    ['symbols', 'EUR/USD', /letters, digits/],
  ])('rejects %s=%s', (name, value, message) => {
    const parsed = parseBacktestForm(formOf({ [name]: value }));
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) expect(parsed.errors[name as keyof typeof parsed.errors]).toMatch(message);
  });

  it('needs 2 symbols for a symbol split and caps the symbol count', () => {
    const one = parseBacktestForm(formOf({ symbols: 'EURUSD', split: 'symbols' }));
    expect(!one.ok && one.errors.split).toMatch(/at least 2/);
    const many = Array.from({ length: 51 }, (_, i) => `S${i}`).join(' ');
    const tooMany = parseBacktestForm(formOf({ symbols: many }));
    expect(!tooMany.ok && tooMany.errors.symbols).toMatch(/at most 50/);
  });

  it('enforces the cost cap symbols x bars x bars / stride <= 1.2e8', () => {
    const four = 'A B C D';
    const five = 'A B C D E';
    expect(parseBacktestForm(formOf({ symbols: four, bars: '5000' })).ok).toBe(true);
    const over = parseBacktestForm(formOf({ symbols: five, bars: '5000' }));
    expect(!over.ok && over.errors.bars).toMatch(/Too large/);
    expect(parseBacktestForm(formOf({ symbols: five, bars: '5000', stride: '2' })).ok).toBe(true);
  });

  it('allows a run exactly at the cost cap and rejects one symbol more', () => {
    const symbols = (count: number) => Array.from({ length: count }, (_, i) => `S${i}`).join(' ');
    // 40 x 3000 x 3000 / 3 = 1.2e8.
    expect(parseBacktestForm(formOf({ symbols: symbols(40), bars: '3000', stride: '3' })).ok).toBe(
      true
    );
    const over = parseBacktestForm(formOf({ symbols: symbols(41), bars: '3000', stride: '3' }));
    expect(!over.ok && over.errors.bars).toMatch(/Too large/);
  });

  it('leaves the cost cap to the API when no symbols are given', () => {
    expect(parseBacktestForm(formOf({ symbols: '', bars: '5000' })).ok).toBe(true);
  });

  it('rejects an over-long field instead of cutting it', () => {
    const parsed = parseBacktestForm(formOf({ symbols: 'AB '.repeat(700) }));
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) expect(parsed.errors.symbols).toBe('Use at most 2000 characters.');
  });
});

describe('form helpers', () => {
  it('reads only known fields, trimmed', () => {
    const form = formOf({ bars: ' 300 ' });
    form.set('evil', 'x');
    const values = readBacktestValues(form);
    expect(values.bars).toBe('300');
    expect(values).not.toHaveProperty('evil');
    expect(readBacktestValues(new FormData()).bars).toBe('');
  });

  it('splits symbols and computes the cost', () => {
    expect(splitSymbols(' A,,B  A ')).toEqual(['A', 'B']);
    expect(backtestCost(4, 5000, 1)).toBe(1e8);
    expect(backtestCost(5, 5000, 2)).toBe(6.25e7);
  });
});
