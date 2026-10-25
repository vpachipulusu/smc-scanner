/** The backtest components render a fixture run with text verdicts, headed tables and a11y text. */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/app/strategies/actions', () => ({
  saveStrategyAction: vi.fn(),
  deleteStrategyAction: vi.fn(),
}));

import { BacktestComparison, comparisonRows } from '@/components/backtests/backtest-comparison';
import { BacktestDetail, headlineStats } from '@/components/backtests/backtest-detail';
import { BacktestEquity, CURVE_NEEDS_EXPORT_MESSAGE } from '@/components/backtests/backtest-equity';
import { BacktestHistory } from '@/components/backtests/backtest-history';
import { runParams } from '@/components/backtests/backtest-params';
import { BacktestRunFields, costText } from '@/components/backtests/backtest-run-fields';
import { BacktestSummary } from '@/components/backtests/backtest-summary';
import { VerdictBadge } from '@/components/backtests/verdict-badge';
import { StrategyPicker, optionLabel } from '@/components/scan/strategy-picker';
import { StrategyList } from '@/components/strategies/strategy-list';
import { BACKTEST_DEFAULTS } from '@/lib/backtests/form';
import type { StrategyOption } from '@/lib/scan/strategy-options';
import { makeBacktest, makeListItem, makeStats } from '../../helpers/backtest-fixtures';
import { BUILTIN, CATALOGUE, makeStrategy } from '../../helpers/strategies-page-fixtures';

describe('VerdictBadge', () => {
  it.each([
    ['survived', 'Survived'],
    ['failed', 'Failed'],
    ['insufficient', 'Insufficient'],
    ['not-run', 'Not run'],
    ['unknown', 'No verdict'],
  ] as const)('says %s in text', (verdict, label) => {
    const { container } = render(<VerdictBadge verdict={verdict} />);
    expect(container).toHaveTextContent(`Backtest verdict: ${label}`);
    expect(container.querySelector(`[data-verdict="${verdict}"]`)).not.toBeNull();
  });
});

describe('BacktestSummary', () => {
  it('renders the out-of-sample cards of a fixture run', () => {
    const run = makeBacktest();
    const { stats, scope } = headlineStats(run);
    render(<BacktestSummary verdict="survived" stats={stats} scope={scope} />);

    expect(screen.getByRole('heading', { name: 'Verdict' })).toBeInTheDocument();
    expect(screen.getByText('Out of sample')).toBeInTheDocument();
    const value = (label: string) => screen.getByText(label).nextElementSibling?.textContent;
    expect(value('Closed trades')).toBe('42');
    expect(value('Hit rate')).toBe('47.6%');
    expect(value('Expectancy')).toBe('+0.31R');
    expect(screen.getByText('95% interval +0.05R to +0.58R')).toBeInTheDocument();
    expect(value('Profit factor')).toBe('1.59');
    expect(value('Max drawdown')).toBe('−4.50R');
    expect(value('Avg bars held')).toBe('12.3');
  });

  it('explains Insufficient and copes with unreadable stats', () => {
    render(<BacktestSummary verdict="insufficient" stats={null} scope="Out of sample" />);
    expect(screen.getByTestId('verdict-description')).toHaveTextContent(/Fewer than 30 closed/);
    expect(screen.getByText(/no readable statistics/)).toBeInTheDocument();
  });

  it('falls back to the pooled stats of a CLI run', () => {
    const run = makeBacktest({ results: { pooled: makeStats({ n: 99 }) } });
    expect(headlineStats(run)).toEqual({
      stats: expect.objectContaining({ n: 99 }),
      scope: 'Pooled (whole run)',
    });
    expect(headlineStats(makeBacktest({ results: null })).stats).toBeNull();
  });
});

describe('BacktestComparison', () => {
  it('has column and row headers for each part the run produced', () => {
    render(<BacktestComparison results={makeBacktest().results!} />);
    const table = screen.getByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Expectancy' })).toBeInTheDocument();
    expect(
      within(table)
        .getAllByRole('rowheader')
        .map((cell) => cell.textContent)
    ).toEqual(['In sample', 'Out of sample', 'Random baseline', 'Flipped baseline']);
    expect(within(table).getByText('No losses')).toBeInTheDocument();
  });

  it('renders nothing without any part', () => {
    expect(comparisonRows({})).toEqual([]);
    const { container } = render(<BacktestComparison results={{ baselines: null }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('BacktestEquity', () => {
  it('says the curve needs a CLI export without per-trade data', () => {
    render(<BacktestEquity trades={null} stats={makeStats()} />);
    expect(screen.getByTestId('curve-unavailable')).toHaveTextContent(CURVE_NEEDS_EXPORT_MESSAGE);
    expect(screen.getByText(/total \+13\.02R over 42 closed trades/)).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('draws the curve with an accessible summary when trades exist', () => {
    render(<BacktestEquity trades={[2, -1, 2]} stats={null} />);
    const chart = screen.getByRole('img', { name: /Backtest equity curve/ });
    expect(chart).toHaveAccessibleName(/3 closed trades, ending at \+3\.00R/);
  });
});

describe('BacktestHistory', () => {
  const items = [
    makeListItem({ id: 9, status: 'running', verdict: null, n: null, expectancy_r: null }),
    makeListItem({ id: 8, status: 'failed', verdict: null, error: 'No symbol could be loaded' }),
    makeListItem({ id: 7 }),
    makeListItem({ id: 6, status: 'pending', verdict: null }),
  ];

  it('lists runs with text statuses and links to the others', () => {
    render(<BacktestHistory slug="my-one" items={items} selectedId={7} />);
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('Running');
    expect(rows[1]).toHaveTextContent('Run failed');
    expect(rows[2]).toHaveTextContent('Survived');
    expect(rows[2]).toHaveTextContent('Shown above');
    expect(rows[3]).toHaveTextContent('Pending');
    expect(within(rows[0]).getByRole('link')).toHaveAttribute(
      'href',
      '/strategies/my-one/backtest?run=9'
    );
  });

  it('says when there are no runs', () => {
    render(<BacktestHistory slug="my-one" items={[]} selectedId={null} />);
    expect(screen.getByTestId('no-backtests')).toBeInTheDocument();
  });
});

describe('BacktestDetail', () => {
  it('shows a finished run in full', () => {
    render(<BacktestDetail run={makeBacktest()} />);
    expect(screen.getByRole('heading', { name: 'Verdict' }).parentElement).toHaveTextContent(
      'Survived'
    );
    expect(screen.getByRole('heading', { name: 'Against the baselines' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Equity curve (R)' })).toBeInTheDocument();
    expect(screen.getByText('EURUSD, XAUUSD')).toBeInTheDocument();
  });

  it('shows the fixed error of a failed run', () => {
    render(
      <BacktestDetail
        run={makeBacktest({
          status: 'failed',
          verdict: null,
          results: null,
          error: 'No symbol could be loaded',
        })}
      />
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/No symbol could be loaded/);
  });

  it('says a run in flight is still going', () => {
    render(
      <BacktestDetail run={makeBacktest({ status: 'running', results: null, verdict: null })} />
    );
    expect(screen.getByTestId('run-in-flight')).toHaveTextContent('This run is running.');
  });

  it('lists the run parameters, with dashes for unreadable rules', () => {
    const params = runParams(
      makeBacktest({ rules: null, symbols: [], split: 'symbols', duration_seconds: null })
    );
    const value = (label: string) => params.find((p) => p.label === label)?.value;
    expect(value('Symbols')).toBe('Watchlist');
    expect(value('Reward to risk')).toBe('—');
    expect(value('Split')).toBe('By symbol');
    expect(value('Duration')).toBe('—');
    expect(value('Started')).toBe('2026-10-20 08:30 UTC');
  });
});

describe('BacktestRunFields', () => {
  it('shows the cost as the size fields change', async () => {
    const user = userEvent.setup();
    render(<BacktestRunFields values={BACKTEST_DEFAULTS} errors={{}} />);
    expect(screen.getByTestId('backtest-cost')).toHaveTextContent(/Cost cap: .* at most 1.2e8/);

    await user.type(screen.getByLabelText('Symbols'), 'A B C D E');
    await user.clear(screen.getByLabelText('Bars'));
    await user.type(screen.getByLabelText('Bars'), '5000');
    expect(screen.getByTestId('backtest-cost')).toHaveTextContent(
      'Cost: 5 × 5000 × 5000 ÷ 1 = 1.3e8 of at most 1.2e8. Too large'
    );
    await user.clear(screen.getByLabelText('Stride'));
    await user.type(screen.getByLabelText('Stride'), '2');
    expect(screen.getByTestId('backtest-cost')).not.toHaveTextContent('Too large');
  });

  it('links field errors and hints', () => {
    render(<BacktestRunFields values={BACKTEST_DEFAULTS} errors={{ seed: 'Enter a number.' }} />);
    const seed = screen.getByLabelText('Seed');
    expect(seed).toHaveAttribute('aria-invalid', 'true');
    expect(seed).toHaveAccessibleDescription(/data snooping.*Enter a number\./);
  });

  it('only counts known sizes in the cost', () => {
    expect(costText('A', 'x', '1').over).toBe(false);
    expect(costText('', '5000', '1').text).toMatch(/watchlist/);
  });
});

describe('verdict badges in the strategy list and picker', () => {
  const options: StrategyOption[] = [
    {
      slug: 'smc-default',
      name: 'SMC default',
      builtin: true,
      swingLength: 10,
      nearAtr: 0.5,
      mtf: false,
    },
    { slug: 'my-one', name: 'Mine', builtin: false, swingLength: 8, nearAtr: 0.3, mtf: false },
  ];

  it('names each option’s verdict and shows the picked one’s badge', () => {
    render(
      <StrategyPicker
        id="p"
        name="strategy"
        options={options}
        defaultValue="smc-default"
        verdicts={{ 'smc-default': 'survived' }}
      />
    );
    expect(screen.getByRole('option', { name: 'SMC default · Survived' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Mine' })).toBeInTheDocument();
    expect(screen.getByText(/Latest backtest:/)).toHaveTextContent(/^Latest backtest: Survived$/);
    expect(optionLabel(options[1], { 'my-one': 'not-run' })).toBe('Mine · Not run');
  });

  it('links each listed strategy’s badge to its backtest page', () => {
    render(
      <StrategyList
        strategies={[BUILTIN, makeStrategy()]}
        catalogue={CATALOGUE}
        verdicts={{ [BUILTIN.slug]: 'insufficient' }}
      />
    );
    const link = screen.getByRole('link', {
      name: `Backtest results of ${BUILTIN.name}: Insufficient`,
    });
    expect(link).toHaveAttribute('href', `/strategies/${BUILTIN.slug}/backtest`);
    expect(screen.getAllByRole('link', { name: /^Backtest: / })).toHaveLength(2);
  });
});
