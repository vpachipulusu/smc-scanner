/** Scan form toggles, the HTF column and the timeframes summary. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ScanForm } from '@/components/scan/scan-form';
import { ScanTable } from '@/components/scan/scan-table';
import { DEFAULTS, type ScanPageParams } from '@/lib/scan/params';
import { makeRow } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ analyseScanAction: vi.fn() }));
vi.mock('@/app/scan/actions', () => ({ analyseScanAction: mocks.analyseScanAction }));

import { ScanAnalysis } from '@/components/scan/scan-analysis';

const MTF = 'Include higher/lower timeframe context';
const REQUIRE = 'Require higher-timeframe alignment';

function params(overrides: Partial<ScanPageParams['query']> = {}): ScanPageParams {
  return { query: { ...DEFAULTS, ...overrides }, every: 0 };
}

describe('ScanForm multi-timeframe options', () => {
  it('starts with both options off and the second disabled', () => {
    render(<ScanForm params={params()} config={null} />);

    expect(screen.getByLabelText(MTF)).not.toBeChecked();
    expect(screen.getByLabelText(MTF)).toHaveAttribute('name', 'mtf');
    expect(screen.getByLabelText(REQUIRE)).not.toBeChecked();
    expect(screen.getByLabelText(REQUIRE)).toBeDisabled();
    expect(screen.getByLabelText(REQUIRE)).toHaveAttribute('name', 'htf');
  });

  it('explains the token cost in helper text linked to the checkbox', () => {
    render(<ScanForm params={params()} config={null} />);

    const hint = screen.getByText(/roughly triples/i);
    expect(screen.getByLabelText(MTF)).toHaveAccessibleDescription(hint.textContent ?? '');
  });

  it('enables the second option with the first, and clears it when the first goes off', async () => {
    const user = userEvent.setup();
    render(<ScanForm params={params()} config={null} />);

    await user.click(screen.getByLabelText(MTF));
    expect(screen.getByLabelText(REQUIRE)).toBeEnabled();
    await user.click(screen.getByLabelText(REQUIRE));
    expect(screen.getByLabelText(REQUIRE)).toBeChecked();
    await user.click(screen.getByLabelText(MTF));
    expect(screen.getByLabelText(REQUIRE)).toBeDisabled();
    expect(screen.getByLabelText(REQUIRE)).not.toBeChecked();
  });

  it('reflects the current search params', () => {
    render(<ScanForm params={params({ mtf: true, requireHtfAligned: true })} config={null} />);

    expect(screen.getByLabelText(MTF)).toBeChecked();
    expect(screen.getByLabelText(REQUIRE)).toBeChecked();
    expect(screen.getByLabelText(REQUIRE)).toBeEnabled();
  });

  it('offers Reset when only an mtf option differs from the default', () => {
    render(<ScanForm params={params({ mtf: true })} config={null} />);

    expect(screen.getByRole('link', { name: 'Reset' })).toBeInTheDocument();
  });
});

describe('ScanTable HTF column', () => {
  it('is absent by default', () => {
    render(<ScanTable rows={[makeRow()]} />);

    expect(screen.queryByRole('columnheader', { name: 'HTF' })).not.toBeInTheDocument();
  });

  it('shows the alignment of each row, n/a without an HTF bias', () => {
    render(
      <ScanTable
        showHtf
        rows={[
          makeRow({ zone: 'bull OB', htf_bias: 'bullish' }),
          makeRow({ zone: 'bull OB', htf_bias: 'bearish' }),
          makeRow({ zone: 'bull OB', htf_bias: 'range' }),
          makeRow({ zone: 'bull OB', htf_bias: null }),
        ]}
      />
    );

    expect(screen.getByRole('columnheader', { name: 'HTF' })).toBeInTheDocument();
    const rows = screen.getAllByTestId('scan-row');
    expect(within(rows[0]).getByText('Aligned')).toBeInTheDocument();
    expect(within(rows[1]).getByText('Against HTF')).toBeInTheDocument();
    expect(within(rows[2]).getByText('HTF range')).toBeInTheDocument();
    expect(within(rows[3]).getByText('n/a')).toBeInTheDocument();
  });
});

describe('ScanAnalysis timeframes summary', () => {
  beforeEach(() => mocks.analyseScanAction.mockReset());

  function setup(query: Partial<ScanPageParams['query']>) {
    return render(
      <ScanAnalysis
        params={params(query)}
        rows={[makeRow({ htf_bias: 'bearish' })]}
        failures={[]}
        aiEnabled
      />
    );
  }

  it('shows nothing when mtf is off', () => {
    setup({});

    expect(screen.queryByTestId('mtf-summary')).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'HTF' })).not.toBeInTheDocument();
  });

  it('lists the timeframes used and notes that alignment is not scored', () => {
    setup({ tf: '1h', mtf: true });

    const summary = screen.getByTestId('mtf-summary');
    expect(summary).toHaveTextContent('Timeframes used: 1h, 4h, 30m');
    expect(summary).toHaveTextContent('Higher timeframe: 4h');
    expect(summary).toHaveTextContent('not part of the 0-4 score');
    expect(screen.getByRole('columnheader', { name: 'HTF' })).toBeInTheDocument();
  });

  it('says n/a for the higher timeframe on 1d', () => {
    setup({ tf: '1d', mtf: true });

    expect(screen.getByTestId('mtf-summary')).toHaveTextContent('Higher timeframe: n/a');
  });

  it('mentions the filter when alignment is required', () => {
    setup({ tf: '1h', mtf: true, requireHtfAligned: true });

    expect(screen.getByTestId('mtf-summary')).toHaveTextContent(/does not confirm are hidden/i);
  });
});
