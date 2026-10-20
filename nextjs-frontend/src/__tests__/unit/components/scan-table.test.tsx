/** The results table: status and bias pills, score pips, yes/no ticks, exact prices. */
import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { ScanTable, formatPrice } from '@/components/scan/scan-table';
import { makeAnalysedRow, makeRow } from '../../helpers/fixtures';

describe('ScanTable', () => {
  it('renders one row per hit with the instrument and zone', () => {
    render(
      <ScanTable
        rows={[makeRow(), makeRow({ instrument: 'XAUUSD', zone: 'bull OB', status: 'NEAR' })]}
      />
    );

    const rows = screen.getAllByTestId('scan-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('EURUSD')).toBeInTheDocument();
    expect(within(rows[1]).getByText('bull OB')).toBeInTheDocument();
  });

  it('shows TOUCHING as a good pill and NEAR as an info pill', () => {
    render(<ScanTable rows={[makeRow(), makeRow({ status: 'NEAR', dist_atr: 0.313 })]} />);

    expect(screen.getByText('TOUCHING').closest('span')).toHaveClass('bg-good');
    expect(screen.getByText('NEAR').closest('span')).toHaveClass('bg-info');
    expect(screen.getByText('0.31')).toBeInTheDocument();
  });

  it('colours the bias pill by direction', () => {
    render(
      <ScanTable
        rows={[
          makeRow({ bias: 'bullish' }),
          makeRow({ bias: 'bearish' }),
          makeRow({ bias: 'range' }),
        ]}
      />
    );

    expect(screen.getByText('bullish').closest('span')).toHaveClass('bg-good');
    expect(screen.getByText('bearish').closest('span')).toHaveClass('bg-crit');
    expect(screen.getByText('range').closest('span')).toHaveClass('bg-secondary');
  });

  it('draws the score as filled pips plus the number', () => {
    render(<ScanTable rows={[makeRow({ score: 3 })]} />);

    const pips = screen.getByRole('img', { name: 'Score 3 of 4' });
    expect(pips.querySelectorAll('[data-filled="true"]')).toHaveLength(3);
    expect(pips.querySelectorAll('[data-filled="false"]')).toHaveLength(1);
    expect(pips).toHaveTextContent('3');
  });

  it('names each confluence tick for screen readers', () => {
    render(<ScanTable rows={[makeRow({ in_ote: true, trendline_ok: false, ob_fvg: true })]} />);

    expect(screen.getByText('In OTE: yes')).toBeInTheDocument();
    expect(screen.getByText('Trendline holds: no')).toBeInTheDocument();
    expect(screen.getByText('OB and FVG stacked: yes')).toBeInTheDocument();
  });

  it('prints prices at quote precision', () => {
    render(
      <ScanTable rows={[makeRow({ zone_low: 4126.31, zone_high: 4172.56, price: 29572.9 })]} />
    );

    expect(screen.getByText('4126.31')).toBeInTheDocument();
    expect(screen.getByText('4172.56')).toBeInTheDocument();
    expect(screen.getByText('29572.9')).toBeInTheDocument();
  });
});

describe('formatPrice', () => {
  it.each([
    [1.08235, '1.08235'],
    [65432.1, '65432.1'],
    [100, '100'],
    [0.1 + 0.2, '0.3'],
  ])('formats %s as %s', (value, expected) => {
    expect(formatPrice(value)).toBe(expected);
  });
});

describe('ScanTable AI columns', () => {
  it('has no AI columns unless asked for', () => {
    render(<ScanTable rows={[makeAnalysedRow()]} />);

    expect(screen.queryByRole('columnheader', { name: 'Action' })).not.toBeInTheDocument();
    expect(screen.queryByText('BUY')).not.toBeInTheDocument();
  });

  it('shows "no value" for a verdict without setup numbers', () => {
    render(
      <ScanTable
        showAi
        rows={[
          makeAnalysedRow({
            ai: { status: 'analysed', note: '', verdict: { action: 'HOLD', confidence: 40 } },
          }),
          makeRow(),
        ]}
      />
    );

    const [held, plain] = screen.getAllByTestId('scan-row');
    expect(within(held).getByText('HOLD')).toBeInTheDocument();
    expect(within(held).getByText('No verdict')).toBeInTheDocument();
    expect(within(plain).getAllByText('No verdict')).toHaveLength(3);
  });
});
