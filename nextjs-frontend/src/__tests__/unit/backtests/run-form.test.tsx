/** The run form: pending state, errors, Run off while a run is in flight, and the 5 s poll. */
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BacktestPollResult, RunBacktestState } from '@/lib/backtests/state';

const mocks = vi.hoisted(() => ({
  run: vi.fn(),
  poll: vi.fn(),
  router: { push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() },
}));
vi.mock('@/app/strategies/[slug]/backtest/actions', () => ({
  runBacktestAction: (...a: unknown[]) => mocks.run(...a),
  pollBacktestAction: (...a: unknown[]) => mocks.poll(...a),
}));
vi.mock('next/navigation', () => ({ useRouter: () => mocks.router }));

import { BacktestRunForm, RUN_BUSY_HINT } from '@/components/backtests/backtest-run-form';
import {
  MAX_FAILED_POLLS,
  POLL_INTERVAL_MS,
  POLL_STOPPED_MESSAGE,
  RunWatcher,
} from '@/components/backtests/run-watcher';
import {
  BACKTEST_ALREADY_RUNNING_MESSAGE,
  BACKTEST_NOT_FOUND_MESSAGE,
  BACKTESTS_STORE_UNAVAILABLE_MESSAGE,
  MAX_BACKOFF_MS,
} from '@/lib/api/backtests-messages';
import { BACKTEST_DEFAULTS } from '@/lib/backtests/form';

const pollOnce = (result: BacktestPollResult) => mocks.poll.mockResolvedValueOnce(result);
const runButton = () => screen.getByRole('button', { name: /Run backtest|Starting/ });
const tick = (ms = POLL_INTERVAL_MS) => act(async () => vi.advanceTimersByTime(ms));

beforeEach(() => {
  mocks.run.mockReset();
  mocks.poll.mockReset();
  Object.values(mocks.router).forEach((fn) => fn.mockReset());
  window.history.replaceState(null, '', '/');
});

afterEach(() => {
  vi.useRealTimers();
});

describe('BacktestRunForm', () => {
  it('posts the strategy, shows a 409 in the alert region and re-reads the page', async () => {
    const user = userEvent.setup();
    mocks.run.mockResolvedValue({
      status: 'error',
      message: BACKTEST_ALREADY_RUNNING_MESSAGE,
      errors: {},
      values: BACKTEST_DEFAULTS,
    } satisfies RunBacktestState);
    render(<BacktestRunForm slug="my-one" inFlightId={null} />);

    await user.click(runButton());

    // The alert region is always present; wait for its text.
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(BACKTEST_ALREADY_RUNNING_MESSAGE)
    );
    // The run started elsewhere shows up (and turns Run off) once the page is read again.
    await waitFor(() => expect(mocks.router.refresh).toHaveBeenCalled());
    const form = mocks.run.mock.calls[0][1] as FormData;
    expect(form.get('strategy')).toBe('my-one');
    expect(form.get('bars')).toBe('500');
  });

  it('does not re-read the page for a refusal other than 409', async () => {
    const user = userEvent.setup();
    mocks.run.mockResolvedValue({
      status: 'error',
      message: BACKTESTS_STORE_UNAVAILABLE_MESSAGE,
      errors: {},
      values: BACKTEST_DEFAULTS,
    } satisfies RunBacktestState);
    render(<BacktestRunForm slug="my-one" inFlightId={null} />);

    await user.click(runButton());
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(BACKTESTS_STORE_UNAVAILABLE_MESSAGE)
    );
    expect(mocks.router.refresh).not.toHaveBeenCalled();
  });

  it('starts watching a listed run with its listed status', () => {
    render(<BacktestRunForm slug="my-one" inFlightId={4} inFlightStatus="running" />);
    expect(screen.getByTestId('run-watcher')).toHaveTextContent('Backtest running');
  });

  it('shows the pending state, then focuses the first invalid field', async () => {
    const user = userEvent.setup();
    let resolve: (state: RunBacktestState) => void = () => {};
    mocks.run.mockReturnValue(new Promise((done) => (resolve = done)));
    render(<BacktestRunForm slug="my-one" inFlightId={null} />);

    await user.click(runButton());
    expect(await screen.findByRole('button', { name: 'Starting…' })).toHaveAttribute(
      'aria-disabled',
      'true'
    );
    await user.click(runButton());
    expect(mocks.run).toHaveBeenCalledTimes(1);

    await act(async () =>
      resolve({
        status: 'error',
        errors: { bars: 'Enter a number from 15 to 5000.' },
        values: { ...BACKTEST_DEFAULTS, bars: '1' },
      })
    );
    expect(screen.getByLabelText('Bars')).toHaveFocus();
    expect(screen.getByLabelText('Bars')).toHaveValue(1);
    expect(mocks.router.refresh).not.toHaveBeenCalled();
  });

  it('keeps Run off but focusable while a listed run is in flight', async () => {
    const user = userEvent.setup();
    render(<BacktestRunForm slug="my-one" inFlightId={4} />);

    expect(runButton()).toHaveAttribute('aria-disabled', 'true');
    expect(runButton()).not.toBeDisabled();
    expect(screen.getByText(RUN_BUSY_HINT)).toBeInTheDocument();
    expect(screen.getByRole('status')).toContainElement(screen.getByTestId('run-watcher'));
    await user.click(runButton());
    expect(mocks.run).not.toHaveBeenCalled();
  });

  it('after a 202 polls every 5 s, moves to the run when it ends and stops', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mocks.run.mockResolvedValue({ status: 'started', id: 12, values: BACKTEST_DEFAULTS });
    pollOnce({ ok: true, status: 'running' });
    pollOnce({ ok: true, status: 'done' });
    render(<BacktestRunForm slug="my-one" inFlightId={null} />);

    await user.click(runButton());
    expect(await screen.findByTestId('run-watcher')).toBeInTheDocument();
    await waitFor(() => expect(mocks.router.refresh).toHaveBeenCalledTimes(1));
    expect(runButton()).toHaveAttribute('aria-disabled', 'true');

    await tick();
    expect(mocks.poll).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('run-watcher')).toHaveTextContent('Backtest running');

    await tick();
    expect(mocks.poll).toHaveBeenCalledTimes(2);
    expect(mocks.poll).toHaveBeenCalledWith(12);
    expect(mocks.router.replace).toHaveBeenCalledWith('/strategies/my-one/backtest?run=12', {
      scroll: false,
    });
    await waitFor(() => expect(runButton()).toHaveAttribute('aria-disabled', 'false'));

    await tick(POLL_INTERVAL_MS * 3);
    expect(mocks.poll).toHaveBeenCalledTimes(2);
  });

  it('refreshes instead of navigating when the page already shows that run', async () => {
    vi.useFakeTimers();
    window.history.replaceState(null, '', '/strategies/my-one/backtest?run=4');
    pollOnce({ ok: true, status: 'failed' });
    render(<BacktestRunForm slug="my-one" inFlightId={4} />);

    await tick();
    expect(mocks.router.refresh).toHaveBeenCalledTimes(1);
    expect(mocks.router.replace).not.toHaveBeenCalled();
  });

  it('watches a newer listed run once the one started here has ended', async () => {
    vi.useFakeTimers();
    mocks.run.mockResolvedValue({ status: 'started', id: 12, values: BACKTEST_DEFAULTS });
    pollOnce({ ok: true, status: 'done' });
    const { rerender } = render(<BacktestRunForm slug="my-one" inFlightId={null} />);

    await act(async () => runButton().click());
    expect(screen.getByTestId('run-watcher')).toBeInTheDocument();
    await tick();
    expect(mocks.poll).toHaveBeenCalledWith(12);
    expect(runButton()).toHaveAttribute('aria-disabled', 'false');

    // The refreshed page lists another run in flight (another tab, a schedule).
    rerender(<BacktestRunForm slug="my-one" inFlightId={13} />);
    expect(runButton()).toHaveAttribute('aria-disabled', 'true');
    pollOnce({ ok: true, status: 'running' });
    await tick();
    expect(mocks.poll).toHaveBeenLastCalledWith(13);
  });

  it('only refreshes when the run is gone', async () => {
    vi.useFakeTimers();
    pollOnce({ ok: false, message: 'That backtest no longer exists.', gone: true });
    render(<BacktestRunForm slug="my-one" inFlightId={8} />);

    await tick();
    expect(mocks.router.refresh).toHaveBeenCalledTimes(1);
    expect(mocks.router.replace).not.toHaveBeenCalled();
    expect(runButton()).toHaveAttribute('aria-disabled', 'false');
    expect(screen.getByRole('status')).toHaveTextContent(BACKTEST_NOT_FOUND_MESSAGE);
  });
});

describe('RunWatcher', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it('waits for Retry-After on a 429 and shows the message', async () => {
    const onFinish = vi.fn();
    pollOnce({ ok: false, message: 'Too many backtest requests.', gone: false, retryAfter: 20 });
    pollOnce({ ok: true, status: 'failed' });
    render(<RunWatcher id={3} onFinish={onFinish} />);

    await tick();
    expect(screen.getByText('Too many backtest requests.')).toBeInTheDocument();
    await tick(19_999);
    expect(mocks.poll).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(mocks.poll).toHaveBeenCalledTimes(2);
    expect(onFinish).toHaveBeenCalledWith(3, 'failed');
    expect(screen.getByTestId('run-watcher')).toHaveTextContent('Backtest failed');
  });

  it('caps a huge Retry-After at five minutes and ignores 0', async () => {
    pollOnce({ ok: false, message: 'slow', gone: false, retryAfter: 999999 });
    pollOnce({ ok: false, message: 'slow', gone: false, retryAfter: 0 });
    pollOnce({ ok: true, status: 'running' });
    render(<RunWatcher id={3} onFinish={vi.fn()} />);

    await tick();
    await tick(MAX_BACKOFF_MS - 1);
    expect(mocks.poll).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(mocks.poll).toHaveBeenCalledTimes(2);
    await tick();
    expect(mocks.poll).toHaveBeenCalledTimes(3);
  });

  it('keeps going after a thrown poll and reports a run that is gone', async () => {
    const onFinish = vi.fn();
    mocks.poll.mockRejectedValueOnce(new Error('network'));
    pollOnce({ ok: false, message: 'That backtest no longer exists.', gone: true });
    render(<RunWatcher id={5} onFinish={onFinish} />);

    await tick();
    expect(screen.getByText(/backtest request failed/)).toBeInTheDocument();
    await tick();
    expect(onFinish).toHaveBeenCalledWith(5, 'gone');
    await tick(POLL_INTERVAL_MS * 3);
    expect(mocks.poll).toHaveBeenCalledTimes(2);
  });

  it('stops after repeated failures and says so', async () => {
    mocks.poll.mockResolvedValue({ ok: false, message: 'down', gone: false });
    render(<RunWatcher id={6} onFinish={vi.fn()} />);

    for (let i = 0; i < MAX_FAILED_POLLS + 3; i += 1) await tick();
    expect(mocks.poll).toHaveBeenCalledTimes(MAX_FAILED_POLLS);
    expect(screen.getByText(POLL_STOPPED_MESSAGE)).toBeInTheDocument();
  });

  it('does not poll while the tab is hidden', async () => {
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    pollOnce({ ok: true, status: 'running' });
    render(<RunWatcher id={7} onFinish={vi.fn()} />);

    await tick(POLL_INTERVAL_MS * 3);
    expect(mocks.poll).not.toHaveBeenCalled();
    visibility.mockReturnValue('visible');
    await tick();
    expect(mocks.poll).toHaveBeenCalledTimes(1);
    visibility.mockRestore();
  });

  it('stops polling when unmounted', async () => {
    const { unmount } = render(<RunWatcher id={9} onFinish={vi.fn()} />);
    unmount();
    await tick(POLL_INTERVAL_MS * 3);
    expect(mocks.poll).not.toHaveBeenCalled();
  });
});
