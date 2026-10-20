/** The GET form: options from /config (or the constants), current values selected, Reset only when needed. */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ScanForm } from '@/components/scan/scan-form';
import type { ConfigResponse } from '@/lib/api/scan';
import { DEFAULTS, type ScanPageParams } from '@/lib/scan/params';

const CONFIG: ConfigResponse = {
  sources: ['mt5', 'demo'],
  timeframes: ['15m', '1h'],
  defaults: { source: 'mt5', tf: '1h', bars: 500, swing: 10, near: 0.5 },
  limits: { min_bars: 15, max_bars: 5000, max_swing: 100, max_near: 5, max_symbols: 50 },
  watchlist: { mt5: ['EURUSD', 'USTEC'], demo: ['EURUSD'] },
};

const DEFAULT_PARAMS: ScanPageParams = { query: DEFAULTS, every: 0 };

describe('ScanForm', () => {
  it('submits to /scan with GET and shows the current values', () => {
    render(
      <ScanForm
        params={{
          query: {
            ...DEFAULTS,
            source: 'demo',
            tf: '15m',
            symbols: ['EURUSD', 'XAUUSD'],
            bars: 300,
            allTouches: true,
          },
          every: 15,
        }}
        config={CONFIG}
      />
    );

    const form = screen.getByRole('search', { name: 'Scan options' });
    expect(form).toHaveAttribute('action', '/scan');
    expect(form).toHaveAttribute('method', 'get');
    expect(screen.getByLabelText('Source')).toHaveValue('demo');
    expect(screen.getByLabelText('Timeframe')).toHaveValue('15m');
    expect(screen.getByLabelText('Symbols')).toHaveValue('EURUSD, XAUUSD');
    expect(screen.getByLabelText('Bars')).toHaveValue(300);
    expect(screen.getByLabelText('Rescan every (min)')).toHaveValue(15);
    expect(screen.getByLabelText('Include zones touched before')).toBeChecked();
    expect(screen.getByRole('button', { name: 'Scan' })).toHaveAttribute('type', 'submit');
  });

  it('lists the API choices and the watchlist for the chosen source', () => {
    render(<ScanForm params={DEFAULT_PARAMS} config={CONFIG} />);

    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual([
      'mt5',
      'demo',
      '15m',
      '1h',
    ]);
    expect(screen.getByLabelText('Symbols')).toHaveAttribute(
      'placeholder',
      'watchlist: EURUSD, USTEC'
    );
  });

  it('falls back to the built-in choices when the config is unavailable', () => {
    render(<ScanForm params={DEFAULT_PARAMS} config={null} />);

    expect(screen.getAllByRole('option')).toHaveLength(8);
    expect(screen.getByLabelText('Symbols')).toHaveAttribute(
      'placeholder',
      'watchlist (see watchlist.yaml)'
    );
  });

  it('offers Reset only when something differs from the defaults', () => {
    const { rerender } = render(<ScanForm params={DEFAULT_PARAMS} config={CONFIG} />);
    expect(screen.queryByRole('link', { name: 'Reset' })).toBeNull();

    rerender(<ScanForm params={{ query: DEFAULTS, every: 5 }} config={CONFIG} />);
    expect(screen.getByRole('link', { name: 'Reset' })).toHaveAttribute('href', '/scan');
  });
});
