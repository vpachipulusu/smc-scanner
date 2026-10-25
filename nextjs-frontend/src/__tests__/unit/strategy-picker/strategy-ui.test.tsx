/** The strategy picker in both forms, condition chips on scan rows, the schedule list and the detail page. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { makeAnalysis, makeRow } from '../../helpers/fixtures';
import { makeSchedule } from '../../helpers/automation-fixtures';
import { OPTIONS } from '../../helpers/strategy-fixtures';

const mocks = vi.hoisted(() => ({
  saveScheduleAction: vi.fn(),
  toggleScheduleAction: vi.fn(),
  runScheduleAction: vi.fn(),
  deleteScheduleAction: vi.fn(),
}));
vi.mock('@/app/automation/actions', () => mocks);

import { AnalysisDetail, strategyLabel } from '@/components/analyses/analysis-detail';
import { ScheduleForm, SCHEDULE_STRATEGY_HINT } from '@/components/automation/schedule-form';
import { SchedulesTable, STRATEGY_MISSING_PILL } from '@/components/automation/schedules-table';
import { ScanForm } from '@/components/scan/scan-form';
import { ScanTable } from '@/components/scan/scan-table';
import { STRATEGY_PREFILL_HINT } from '@/components/scan/strategy-fields';
import {
  STRATEGY_MISSING_HINT,
  STRATEGY_MTF_HINT,
  StrategyPicker,
} from '@/components/scan/strategy-picker';
import { DEFAULTS } from '@/lib/scan/params';

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
});

describe('StrategyPicker', () => {
  it('groups built-in and custom strategies and links its hints', () => {
    render(
      <StrategyPicker
        id="p"
        name="strategy"
        options={OPTIONS}
        defaultValue="smc-default"
        hint="Pick one."
      />
    );

    const select = screen.getByLabelText('Strategy');
    expect(select).toHaveValue('smc-default');
    expect(select).toHaveAttribute('aria-describedby', 'p-hint');
    const builtin = screen.getByRole('group', { name: 'Built-in' });
    expect(
      within(builtin)
        .getAllByRole('option')
        .map((o) => o.textContent)
    ).toEqual(['SMC default', 'HTF aligned touch']);
    const custom = screen.getByRole('group', { name: 'Custom' });
    expect(within(custom).getByRole('option', { name: 'My setup' })).toHaveValue('my-setup');
  });

  it('shows the MTF hint for a strategy that implies it', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <StrategyPicker
        id="p"
        name="strategy"
        options={OPTIONS}
        defaultValue="smc-default"
        onSelect={onSelect}
      />
    );
    expect(screen.queryByText(STRATEGY_MTF_HINT)).toBeNull();

    await user.selectOptions(screen.getByLabelText('Strategy'), 'htf-aligned-touch');

    expect(screen.getByText(STRATEGY_MTF_HINT)).toHaveAttribute('id', 'p-mtf-hint');
    expect(screen.getByLabelText('Strategy')).toHaveAttribute('aria-describedby', 'p-mtf-hint');
    expect(onSelect).toHaveBeenCalledWith(OPTIONS[1]);
  });

  it('keeps and flags a strategy that is not in the list', () => {
    render(
      <StrategyPicker id="p" name="strategy" options={OPTIONS} defaultValue="gone" error="Bad." />
    );

    const select = screen.getByLabelText('Strategy');
    expect(select).toHaveValue('gone');
    expect(screen.getByRole('option', { name: 'gone (not found)' })).toBeInTheDocument();
    expect(screen.getByText(STRATEGY_MISSING_HINT)).toBeInTheDocument();
    expect(select).toHaveAttribute('aria-invalid', 'true');
    expect(select).toHaveAttribute('aria-describedby', 'p-missing p-error');
  });

  it('does not flag an unknown slug when only part of the list loaded', () => {
    render(
      <StrategyPicker
        id="p"
        name="strategy"
        options={OPTIONS}
        defaultValue="mine"
        complete={false}
      />
    );
    expect(screen.getByRole('option', { name: 'mine' })).toBeInTheDocument();
    expect(screen.queryByText(STRATEGY_MISSING_HINT)).toBeNull();
  });

  it('offers only the current slug, unflagged, when no list loaded', () => {
    render(<StrategyPicker id="p" name="strategy" options={[]} defaultValue="smc-default" />);

    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['smc-default']);
    expect(screen.queryByText(STRATEGY_MISSING_HINT)).toBeNull();
  });
});

describe('ScanForm strategy', () => {
  it('prefills swing and near from the picked strategy, and the user can still change them', async () => {
    const user = userEvent.setup();
    render(<ScanForm params={{ query: DEFAULTS, every: 0 }} config={null} strategies={OPTIONS} />);
    expect(screen.getByText(STRATEGY_PREFILL_HINT)).toBeInTheDocument();
    const swing = screen.getByLabelText('Swing length');
    const near = screen.getByLabelText('Near (ATR)');
    expect(swing).toHaveValue(10);

    await user.selectOptions(screen.getByLabelText('Strategy'), 'my-setup');
    expect(swing).toHaveValue(5);
    expect(near).toHaveValue(1);

    await user.clear(swing);
    await user.type(swing, '12');
    expect(swing).toHaveValue(12);
    expect(screen.getByLabelText('Strategy')).toHaveAttribute('name', 'strategy');
  });

  it('selects the URL strategy', () => {
    render(
      <ScanForm
        params={{ query: { ...DEFAULTS, strategy: 'my-setup', swing: 5, near: 1 }, every: 0 }}
        config={null}
        strategies={OPTIONS}
      />
    );
    expect(screen.getByLabelText('Strategy')).toHaveValue('my-setup');
    expect(screen.getByLabelText('Swing length')).toHaveValue(5);
    // Any step, so a prefilled 0.25 never blocks the GET submit.
    expect(screen.getByLabelText('Near (ATR)')).toHaveAttribute('step', 'any');
  });
});

describe('ScheduleForm strategy', () => {
  it('offers the strategies and preselects the schedule one', () => {
    render(<ScheduleForm schedule={makeSchedule({ strategy: 'my-setup' })} strategies={OPTIONS} />);

    const select = screen.getByLabelText('Strategy');
    expect(select).toHaveValue('my-setup');
    expect(select).toHaveAttribute('name', 'strategy');
    expect(screen.getByText(SCHEDULE_STRATEGY_HINT)).toBeInTheDocument();
    expect(SCHEDULE_STRATEGY_HINT).toMatch(/strategy's swing length and near distance/);
  });

  it('defaults a new schedule to smc-default and shows the MTF hint when picked', async () => {
    const user = userEvent.setup();
    render(<ScheduleForm strategies={OPTIONS} />);
    expect(screen.getByLabelText('Strategy')).toHaveValue('smc-default');

    await user.selectOptions(screen.getByLabelText('Strategy'), 'htf-aligned-touch');

    expect(screen.getByText(STRATEGY_MTF_HINT)).toBeInTheDocument();
  });
});

describe('ScanTable condition chips', () => {
  const labels = { aligned: 'Aligned with bias', fresh: 'Fresh zone' };

  it('renders one chip per condition, met and unmet told apart by text', () => {
    render(
      <ScanTable
        rows={[makeRow({ conditions: { aligned: true, fresh: false, max_zone_age: true } })]}
        conditionLabels={labels}
      />
    );

    expect(screen.getByRole('columnheader', { name: 'Conditions' })).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Strategy conditions' });
    const chips = within(list).getAllByRole('listitem');
    expect(chips.map((chip) => chip.textContent)).toEqual([
      'Aligned with bias: met',
      'Fresh zone: not met',
      'Max zone age: met',
    ]);
    expect(chips.map((chip) => chip.getAttribute('data-met'))).toEqual(['true', 'false', 'true']);
  });

  it('marks a row without conditions next to rows with them', () => {
    render(
      <ScanTable
        rows={[makeRow({ conditions: { fresh: true } }), makeRow({ instrument: 'XAUUSD' })]}
      />
    );
    expect(screen.getByText('No conditions')).toBeInTheDocument();
  });

  it('hides the column when no row carries conditions', () => {
    render(<ScanTable rows={[makeRow(), makeRow({ conditions: {} })]} />);
    expect(screen.queryByRole('columnheader', { name: 'Conditions' })).toBeNull();
  });
});

describe('SchedulesTable strategy', () => {
  it('shows each strategy slug and flags a deleted one', () => {
    render(
      <SchedulesTable
        schedules={[
          makeSchedule({ id: 1 }),
          makeSchedule({ id: 2, name: 'Custom', strategy: 'my-setup' }),
          makeSchedule({ id: 3, name: 'Old', strategy: 'gone' }),
        ]}
        knownStrategies={new Set(['smc-default', 'my-setup'])}
      />
    );

    expect(screen.getByText('smc-default')).toBeInTheDocument();
    expect(screen.getByText('my-setup')).toBeInTheDocument();
    expect(screen.getByText('gone')).toBeInTheDocument();
    expect(screen.getAllByText(STRATEGY_MISSING_PILL)).toHaveLength(1);
  });

  it('flags nothing when the strategy list is unknown', () => {
    render(<SchedulesTable schedules={[makeSchedule({ strategy: 'gone' })]} />);
    expect(screen.queryByText(STRATEGY_MISSING_PILL)).toBeNull();
  });
});

describe('AnalysisDetail strategy', () => {
  it('shows the strategy name with its slug', () => {
    render(
      <AnalysisDetail analysis={makeAnalysis({ strategy: 'my-setup' })} strategyName="My setup" />
    );
    expect(screen.getByText('My setup (my-setup)')).toBeInTheDocument();
  });

  it('falls back to the slug, and older rows read as the default', () => {
    expect(strategyLabel(makeAnalysis({ strategy: 'gone' }))).toBe('gone');
    expect(strategyLabel(makeAnalysis())).toBe('smc-default');
    expect(strategyLabel(makeAnalysis(), '  ')).toBe('smc-default');
    expect(strategyLabel(makeAnalysis({ strategy: 'x' }), 'x')).toBe('x');
  });
});
