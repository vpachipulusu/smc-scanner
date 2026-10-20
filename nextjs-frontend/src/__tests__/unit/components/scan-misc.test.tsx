/** Failures panel, load error and the auto-refresh line. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { AutoRefresh, formatScanTime } from '@/components/scan/auto-refresh';
import { ScanFailures } from '@/components/scan/scan-failures';
import { ScanLoadError } from '@/components/scan/scan-load-error';
import { FAILURE } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));

describe('ScanFailures', () => {
  it('renders nothing without failures', () => {
    const { container } = render(<ScanFailures failures={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('lists each skipped symbol with its reason', () => {
    render(<ScanFailures failures={[FAILURE, { symbol: 'NAS100', error: 'no candles' }]} />);

    const panel = screen.getByTestId('scan-failures');
    expect(panel).toHaveTextContent('2 symbols skipped');
    expect(panel).toHaveTextContent('BTCUSD');
    expect(panel).toHaveTextContent("unknown symbol 'BTCUSD'");
    expect(panel).toHaveTextContent('NAS100');
  });

  it('uses the singular for one failure', () => {
    render(<ScanFailures failures={[FAILURE]} />);
    expect(screen.getByRole('heading')).toHaveTextContent('1 symbol skipped');
  });
});

describe('ScanLoadError', () => {
  it('shows the message as an alert with a retry link', () => {
    render(<ScanLoadError message="Backend down" retryHref="/scan?tf=5m" />);

    expect(screen.getByRole('alert')).toHaveTextContent('Backend down');
    expect(screen.getByRole('link', { name: 'Retry' })).toHaveAttribute('href', '/scan?tf=5m');
  });
});

describe('AutoRefresh', () => {
  afterEach(() => {
    vi.useRealTimers();
    mocks.refresh.mockReset();
  });

  it('formats the scan time in UTC', () => {
    expect(formatScanTime('2026-10-20T01:02:03.000Z')).toBe('01:02:03 UTC');
    expect(formatScanTime('not a date')).toBe('—');
  });

  it('shows only the last scan time when rescanning is off', () => {
    render(<AutoRefresh everyMinutes={0} scannedAt="2026-10-20T01:02:03Z" stopHref="/scan" />);

    expect(screen.getByTestId('scanned-at')).toHaveTextContent('Last scan at 01:02:03 UTC');
    expect(screen.queryByTestId('auto-refresh')).toBeNull();
    expect(screen.queryByRole('link', { name: 'Stop' })).toBeNull();
  });

  it('refreshes the page every N minutes and offers to stop', () => {
    vi.useFakeTimers();
    render(
      <AutoRefresh everyMinutes={2} scannedAt="2026-10-20T01:02:03Z" stopHref="/scan?tf=5m" />
    );

    expect(screen.getByTestId('auto-refresh')).toHaveTextContent('Rescanning every 2 min');
    expect(screen.getByRole('link', { name: 'Stop' })).toHaveAttribute('href', '/scan?tf=5m');
    act(() => {
      vi.advanceTimersByTime(2 * 60_000 - 1);
    });
    expect(mocks.refresh).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it('clears the timer on unmount', () => {
    vi.useFakeTimers();
    const { unmount } = render(
      <AutoRefresh everyMinutes={1} scannedAt="2026-10-20T01:02:03Z" stopHref="/scan" />
    );

    unmount();
    act(() => {
      vi.advanceTimersByTime(5 * 60_000);
    });

    expect(mocks.refresh).not.toHaveBeenCalled();
  });
});
