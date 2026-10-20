/** The scan results with the AI verdict: button, pending, success, empty, error, 429 and disabled states. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { AnalyseState } from '@/lib/scan/analyse-state';
import { DEFAULTS, type ScanPageParams } from '@/lib/scan/params';
import { FAILURE, makeAnalysedRow, makeRow } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ analyseScanAction: vi.fn() }));
vi.mock('@/app/scan/actions', () => ({ analyseScanAction: mocks.analyseScanAction }));

import { ScanAnalysis } from '@/components/scan/scan-analysis';
import { ANALYSE_DISABLED_HINT, rateLimitMessage } from '@/lib/api/analyse-messages';

const PARAMS: ScanPageParams = {
  query: { ...DEFAULTS, source: 'demo', tf: '15m', symbols: ['EURUSD'], allTouches: true },
  every: 5,
};

function setup(props: { aiEnabled?: boolean } = {}) {
  return render(
    <ScanAnalysis
      params={PARAMS}
      rows={[makeRow(), makeRow({ instrument: 'XAUUSD', zone: 'bull OB' })]}
      failures={[FAILURE]}
      aiEnabled={props.aiEnabled ?? true}
    />
  );
}

const run = () => userEvent.click(screen.getByRole('button', { name: 'Analyse with AI' }));

describe('ScanAnalysis', () => {
  beforeEach(() => mocks.analyseScanAction.mockReset());

  it('shows the scan table and an enabled button before any analysis', () => {
    setup();

    expect(screen.getByRole('button', { name: 'Analyse with AI' })).toBeEnabled();
    expect(screen.getAllByTestId('scan-row')).toHaveLength(2);
    expect(screen.queryByRole('columnheader', { name: 'Action' })).not.toBeInTheDocument();
    expect(screen.getByTestId('scan-failures')).toHaveTextContent('BTCUSD');
  });

  it('carries the scan options in hidden fields', () => {
    const { container } = setup();

    const fields = Object.fromEntries(
      [...container.querySelectorAll<HTMLInputElement>('input[type="hidden"]')].map((input) => [
        input.name,
        input.value,
      ])
    );
    expect(fields).toEqual({
      source: 'demo',
      tf: '15m',
      symbols: 'EURUSD',
      all: '1',
      every: '5',
    });
  });

  it('shows a pending state, keeps the page usable and blocks a second submit', async () => {
    let finish: (state: AnalyseState) => void = () => undefined;
    mocks.analyseScanAction.mockReturnValue(new Promise<AnalyseState>((r) => (finish = r)));
    setup();

    await run();

    const button = await screen.findByRole('button', { name: /Analysing/ });
    expect(button).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent(/Analysing/);
    expect(screen.getByRole('status')).toHaveTextContent(/keep using the page/i);
    expect(screen.getAllByTestId('scan-row')).toHaveLength(2);

    await act(async () => finish({ status: 'idle' }));
    expect(screen.getByRole('button', { name: 'Analyse with AI' })).toBeEnabled();
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('adds Action, Confidence and Setup after a successful analysis', async () => {
    mocks.analyseScanAction.mockResolvedValue({
      status: 'success',
      rows: [
        makeAnalysedRow(),
        makeAnalysedRow({
          instrument: 'XAUUSD',
          ai: { status: 'analysed', note: '', verdict: { action: 'SELL', confidence: 55 } },
        }),
      ],
      failures: [],
    } satisfies AnalyseState);
    setup();

    await run();

    await screen.findByRole('columnheader', { name: 'Action' });
    expect(screen.getByRole('columnheader', { name: 'Confidence' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Setup' })).toBeInTheDocument();
    const [first, second] = screen.getAllByTestId('scan-row');
    expect(within(first).getByText('BUY')).toBeInTheDocument();
    expect(within(first).getByRole('progressbar', { name: 'Confidence' })).toHaveAttribute(
      'aria-valuenow',
      '72'
    );
    expect(first).toHaveTextContent('Entry 1.0975');
    expect(first).toHaveTextContent('Stop 1.0955');
    expect(first).toHaveTextContent('TP 1.101, 1.104');
    expect(first).toHaveTextContent('R:R 1.75');
    expect(within(second).getByText('SELL')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('2 of 2 hits analysed');
    expect(screen.queryByTestId('scan-failures')).not.toBeInTheDocument();
  });

  it('has no Details link until a list route exists', async () => {
    mocks.analyseScanAction.mockResolvedValue({
      status: 'success',
      rows: [makeAnalysedRow()],
      failures: [],
    } satisfies AnalyseState);
    setup();

    await run();

    await screen.findByRole('columnheader', { name: 'Action' });
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Details' })).not.toBeInTheDocument();
  });

  it('leaves an empty, labelled cell for a row without a verdict and lists why in a warning box', async () => {
    mocks.analyseScanAction.mockResolvedValue({
      status: 'success',
      rows: [
        makeAnalysedRow(),
        makeAnalysedRow({
          instrument: 'XAUUSD',
          ai: { status: 'skipped_low_score', note: 'raw backend note', verdict: null },
        }),
        makeAnalysedRow({
          instrument: 'GBPUSD',
          ai: { status: 'failed', note: 'sk-ant-secret provider trace', verdict: null },
        }),
      ],
      failures: [FAILURE],
    } satisfies AnalyseState);
    setup();

    await run();

    await screen.findByRole('columnheader', { name: 'Action' });
    const rows = screen.getAllByTestId('scan-row');
    expect(within(rows[1]).getAllByText('No verdict')).toHaveLength(3);
    expect(within(rows[1]).queryByRole('progressbar')).not.toBeInTheDocument();
    const notice = screen.getByTestId('ai-skipped');
    expect(notice).toHaveTextContent('2 hits without an AI verdict');
    expect(notice).toHaveTextContent('XAUUSD');
    expect(notice).toHaveTextContent('below the score gate');
    expect(notice).toHaveTextContent('GBPUSD');
    expect(notice).toHaveTextContent('no usable verdict');
    expect(document.body).not.toHaveTextContent('sk-ant');
    expect(document.body).not.toHaveTextContent('raw backend note');
    expect(screen.getByTestId('scan-failures')).toHaveTextContent('BTCUSD');
    expect(screen.getByRole('status')).toHaveTextContent('1 of 3 hits analysed');
  });

  it('uses the singular for one hit without a verdict', async () => {
    mocks.analyseScanAction.mockResolvedValue({
      status: 'success',
      rows: [makeAnalysedRow({ ai: { status: 'skipped_cap', note: '', verdict: null } })],
      failures: [],
    } satisfies AnalyseState);
    setup();

    await run();

    expect(await screen.findByTestId('ai-skipped')).toHaveTextContent(
      '1 hit without an AI verdict'
    );
  });

  it('shows the fixed error message and keeps the scan table', async () => {
    mocks.analyseScanAction.mockResolvedValue({
      status: 'error',
      message: 'The AI provider could not analyse these hits. Please try again later.',
    } satisfies AnalyseState);
    setup();

    await run();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The AI provider could not analyse these hits.'
    );
    expect(screen.getAllByTestId('scan-row')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Analyse with AI' })).toBeEnabled();
  });

  it('shows the friendly rate-limit message', async () => {
    mocks.analyseScanAction.mockResolvedValue({
      status: 'error',
      message: rateLimitMessage(120),
    } satisfies AnalyseState);
    setup();

    await run();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'budget or rate limit has been reached. Please try again in about 2 minutes.'
    );
  });

  it('disables the button with a hint when no provider key is configured', async () => {
    setup({ aiEnabled: false });

    const button = screen.getByRole('button', { name: 'Analyse with AI' });
    expect(button).toBeDisabled();
    expect(screen.getByText(ANALYSE_DISABLED_HINT)).toBeInTheDocument();
    expect(button).toHaveAccessibleDescription(ANALYSE_DISABLED_HINT);
    await userEvent.click(button);
    expect(mocks.analyseScanAction).not.toHaveBeenCalled();
  });

  it('renders model-provided text as text, never as markup', async () => {
    mocks.analyseScanAction.mockResolvedValue({
      status: 'success',
      rows: [makeAnalysedRow({ instrument: '<img src=x onerror=alert(1)>' })],
      failures: [],
    } satisfies AnalyseState);
    const { container } = setup();

    await run();

    await waitFor(() => expect(screen.getByRole('columnheader', { name: 'Action' })).toBeVisible());
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getAllByText('<img src=x onerror=alert(1)>').length).toBeGreaterThan(0);
  });
});
