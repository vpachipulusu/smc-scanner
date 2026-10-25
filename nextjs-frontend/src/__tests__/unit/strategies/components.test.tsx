/** The strategy components: the condition builder and its min_score bound, the form, the list and row actions. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { BUILTIN, CATALOGUE, makeStrategy } from '../../helpers/strategy-fixtures';

const mocks = vi.hoisted(() => ({
  saveStrategyAction: vi.fn(),
  deleteStrategyAction: vi.fn(),
}));
vi.mock('@/app/strategies/actions', () => mocks);

import { ConditionBuilder } from '@/components/strategies/condition-builder';
import { ParamInput } from '@/components/strategies/param-input';
import { StrategyActions } from '@/components/strategies/strategy-actions';
import { StrategyForm } from '@/components/strategies/strategy-form';
import { StrategyList } from '@/components/strategies/strategy-list';
import { STRATEGY_BUILTIN_MESSAGE } from '@/lib/api/strategies-write-messages';
import { emptyFormValues, valuesFromStrategy } from '@/lib/strategies/form';

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
});

const group = (label: string) => screen.getByRole('group', { name: new RegExp(label) });

describe('ConditionBuilder', () => {
  const renderBuilder = (minScore = '1', errors = {}) =>
    render(
      <ConditionBuilder
        catalogue={CATALOGUE}
        conditions={valuesFromStrategy(makeStrategy(), CATALOGUE).conditions}
        minScore={minScore}
        errors={errors}
      />
    );

  it('offers Off / Required / Scored for every catalogue condition', () => {
    renderBuilder();

    for (const info of CATALOGUE) {
      const radios = within(group(info.label)).getAllByRole('radio');
      expect(radios.map((radio) => radio.getAttribute('value'))).toEqual([
        'off',
        'require',
        'score',
      ]);
    }
    expect(within(group('First touch only')).getByLabelText('Required')).toBeChecked();
    expect(screen.getByTestId('condition-counts')).toHaveTextContent('1 required, 2 scored');
  });

  it('renders params from the schema and disables them while the condition is off', async () => {
    const user = userEvent.setup();
    renderBuilder();

    const bars = screen.getByLabelText('Bars');
    expect(bars).toHaveValue(50);
    expect(bars).toBeEnabled();
    expect(bars).toHaveAttribute('max', '5000');
    expect(screen.getByLabelText('Atr')).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Kind' })).toBeDisabled();

    await user.click(within(group('Price within N ATR')).getByLabelText('Required'));
    expect(screen.getByLabelText('Atr')).toBeEnabled();
  });

  it('bounds min_score by the scored count and lowers it when a scored condition goes', async () => {
    const user = userEvent.setup();
    renderBuilder('2');

    const minScore = screen.getByLabelText('Min score');
    expect(minScore).toHaveAttribute('max', '2');
    expect(minScore).toHaveValue(2);

    await user.click(within(group('Zone at most N bars old')).getByLabelText('Off'));

    expect(minScore).toHaveAttribute('max', '1');
    expect(minScore).toHaveValue(1);
    expect(screen.getByTestId('condition-counts')).toHaveTextContent(
      '1 required, 1 scored. Min score lowered to 1.'
    );

    // A change that needs no lowering clears the notice.
    await user.click(within(group('Zone overlaps the OTE band')).getByLabelText('Scored'));
    expect(screen.getByTestId('condition-counts')).toHaveTextContent(/^1 required, 2 scored$/);
  });

  it('says how to unlock min_score when nothing is scored', async () => {
    const user = userEvent.setup();
    renderBuilder('0');

    await user.click(within(group('Zone direction matches the trend')).getByLabelText('Off'));
    await user.click(within(group('Zone at most N bars old')).getByLabelText('Off'));

    expect(
      screen.getByText('Score at least one condition to require a min score.')
    ).toBeInTheDocument();
  });

  it('flags a typed min_score above the bound', async () => {
    const user = userEvent.setup();
    renderBuilder();

    const minScore = screen.getByLabelText('Min score');
    await user.clear(minScore);
    await user.type(minScore, '7');

    expect(minScore).toHaveAttribute('aria-invalid', 'true');
    expect(
      screen.getByText('Enter a whole number from 0 to 2 (the scored conditions).')
    ).toBeInTheDocument();
  });

  it('shows server errors on the condition, its params and the lists', () => {
    renderBuilder('1', {
      'cond.fresh': 'A condition can be used only once.',
      'param.max_zone_age.bars': 'Enter a whole number from 1 to 5000.',
      conditions: 'Use at most 12 conditions.',
      min_score: 'Server says no.',
    });

    expect(screen.getByText('A condition can be used only once.')).toBeInTheDocument();
    expect(screen.getByLabelText('Bars')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('alert')).toHaveTextContent('Use at most 12 conditions.');
    expect(screen.getByText('Server says no.')).toBeInTheDocument();
  });
});

describe('ParamInput', () => {
  it('renders a boolean and a string param', () => {
    render(
      <>
        <ParamInput
          field={{ name: 'on', label: 'On', required: false, kind: 'boolean' }}
          id="p-on"
          name="param.x.on"
          defaultValue="true"
          disabled={false}
          error="Bad"
        />
        <ParamInput
          field={{ name: 'tag', label: 'Tag', required: false, kind: 'string' }}
          id="p-tag"
          name="param.x.tag"
          defaultValue="a"
          disabled={false}
        />
        <ParamInput
          field={{ name: 'n', label: 'N', required: true, kind: 'number', min: 1 }}
          id="p-n"
          name="param.x.n"
          defaultValue=""
          disabled={false}
        />
        <ParamInput
          field={{ name: 'm', label: 'M', required: true, kind: 'number', max: 9 }}
          id="p-m"
          name="param.x.m"
          defaultValue=""
          disabled={false}
        />
      </>
    );

    expect(screen.getByLabelText('On')).toBeChecked();
    expect(screen.getByText('Bad')).toBeInTheDocument();
    expect(screen.getByLabelText('Tag (optional)')).toHaveAttribute('maxLength', '32');
    expect(screen.getByText('at least 1')).toBeInTheDocument();
    expect(screen.getByText('at most 9')).toBeInTheDocument();
  });
});

describe('StrategyForm', () => {
  it('has labelled controls and creates with a slug field', () => {
    render(
      <StrategyForm mode="create" catalogue={CATALOGUE} initial={emptyFormValues(CATALOGUE)} />
    );

    for (const label of [
      'Slug',
      'Name',
      'Description (optional)',
      'Swing length',
      'Near (ATR)',
      'FVG',
      'TOUCHING',
      'Min score',
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Create strategy' })).toBeEnabled();
    expect(screen.getByRole('link', { name: 'Cancel' })).toHaveAttribute('href', '/strategies');
  });

  it('keeps require_htf_aligned off and disabled until mtf is on', async () => {
    const user = userEvent.setup();
    render(
      <StrategyForm mode="create" catalogue={CATALOGUE} initial={emptyFormValues(CATALOGUE)} />
    );

    const requireHtf = screen.getByLabelText('Only rows the higher timeframe confirms');
    expect(requireHtf).toBeDisabled();
    await user.click(screen.getByLabelText('Include higher timeframe context'));
    await user.click(requireHtf);
    expect(requireHtf).toBeChecked();
    await user.click(screen.getByLabelText('Include higher timeframe context'));
    expect(requireHtf).not.toBeChecked();
    expect(requireHtf).toBeDisabled();
  });

  it('edits with the slug fixed in a hidden field', () => {
    const { container } = render(
      <StrategyForm
        mode="edit"
        catalogue={CATALOGUE}
        initial={valuesFromStrategy(makeStrategy(), CATALOGUE)}
      />
    );

    expect(screen.queryByLabelText('Slug')).not.toBeInTheDocument();
    expect(container.querySelector('input[type="hidden"][name="slug"]')).toHaveValue('my-setup');
    expect(container.querySelector('input[type="hidden"][name="mode"]')).toHaveValue('edit');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeInTheDocument();
  });

  it('submits to the action and shows the returned message and field errors', async () => {
    const user = userEvent.setup();
    const values = { ...emptyFormValues(CATALOGUE), name: 'Kept' };
    mocks.saveStrategyAction.mockResolvedValue({
      status: 'error',
      message: STRATEGY_BUILTIN_MESSAGE,
      errors: { slug: 'Slug taken.' },
      values,
    });
    render(
      <StrategyForm mode="create" catalogue={CATALOGUE} initial={emptyFormValues(CATALOGUE)} />
    );

    await user.type(screen.getByLabelText('Name'), 'Kept');
    await user.click(screen.getByRole('button', { name: 'Create strategy' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(STRATEGY_BUILTIN_MESSAGE);
    expect(screen.getByText('Slug taken.')).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Kept');
    await waitFor(() => expect(screen.getByLabelText('Slug')).toHaveFocus());
    const submitted: FormData = mocks.saveStrategyAction.mock.calls[0][1];
    expect(submitted.get('mode')).toBe('create');
    expect(submitted.get('cond.fresh')).toBe('off');
  });

  it('focuses the alert when no field is invalid', async () => {
    const user = userEvent.setup();
    // As when the catalogue is down: no conditions come back, so they keep their initial values.
    mocks.saveStrategyAction.mockResolvedValue({
      status: 'error',
      message: 'Down.',
      errors: {},
      values: { ...emptyFormValues([]), name: 'Typed' },
    });
    render(
      <StrategyForm mode="create" catalogue={CATALOGUE} initial={emptyFormValues(CATALOGUE)} />
    );

    await user.click(screen.getByRole('button', { name: 'Create strategy' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveFocus());
    expect(screen.getByLabelText('Name')).toHaveValue('Typed');
    expect(within(group('First touch only')).getByLabelText('Off')).toBeChecked();
  });

  it('keeps the params of off conditions after a failed submit', async () => {
    const user = userEvent.setup();
    const initial = valuesFromStrategy(makeStrategy(), CATALOGUE);
    const back = valuesFromStrategy(makeStrategy(), CATALOGUE);
    mocks.saveStrategyAction.mockResolvedValue({
      status: 'error',
      errors: { name: 'Enter a name.' },
      values: {
        ...back,
        conditions: {
          ...back.conditions,
          max_zone_age: { mode: 'off', params: { bars: '' } },
        },
      },
    });
    render(<StrategyForm mode="edit" catalogue={CATALOGUE} initial={initial} />);

    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveFocus());
    expect(screen.getByLabelText('Bars')).toHaveValue(50);
    expect(screen.getByLabelText('Bars')).toBeDisabled();
  });

  it('shows an error without a field of its own as the form message', async () => {
    const user = userEvent.setup();
    mocks.saveStrategyAction.mockResolvedValue({
      status: 'error',
      errors: { form: 'Something is off.' },
      values: emptyFormValues(CATALOGUE),
    });
    render(
      <StrategyForm mode="create" catalogue={CATALOGUE} initial={emptyFormValues(CATALOGUE)} />
    );

    await user.click(screen.getByRole('button', { name: 'Create strategy' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Something is off.');
  });
});

describe('StrategyActions', () => {
  it('links scan and duplicate for a built-in, without edit or delete', () => {
    render(<StrategyActions slug="smc-default" name="SMC default" builtin />);

    expect(
      screen.getByRole('link', { name: 'Scan with this strategy: SMC default' })
    ).toHaveAttribute('href', '/scan?strategy=smc-default');
    expect(screen.getByRole('link', { name: 'Duplicate: SMC default' })).toHaveAttribute(
      'href',
      '/strategies/new?from=smc-default'
    );
    expect(screen.queryByRole('link', { name: /Edit/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete/ })).not.toBeInTheDocument();
  });

  it('asks for confirmation, cancels with Escape and returns focus to Delete', async () => {
    const user = userEvent.setup();
    render(<StrategyActions slug="my-setup" name="My setup" builtin={false} />);

    expect(screen.getByRole('link', { name: 'Edit: My setup' })).toHaveAttribute(
      'href',
      '/strategies/my-setup/edit'
    );
    await user.click(screen.getByRole('button', { name: 'Delete: My setup' }));
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await user.keyboard('{Escape}');

    expect(
      screen.queryByRole('form', { name: 'Confirm delete: My setup' })
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete: My setup' })).toHaveFocus();
    expect(mocks.deleteStrategyAction).not.toHaveBeenCalled();
  });

  it('cancels with the Cancel button', async () => {
    const user = userEvent.setup();
    render(<StrategyActions slug="my-setup" name="My setup" builtin={false} />);

    await user.click(screen.getByRole('button', { name: 'Delete: My setup' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('button', { name: 'Confirm delete' })).not.toBeInTheDocument();
  });

  it('posts the slug only after confirming', async () => {
    const user = userEvent.setup();
    // Success redirects in the real action; the mock just settles back to idle.
    mocks.deleteStrategyAction.mockResolvedValue({ status: 'idle' });
    render(<StrategyActions slug="my-setup" name="My setup" builtin={false} />);

    const deleteButton = screen.getByRole('button', { name: 'Delete: My setup' });
    expect(deleteButton).not.toHaveAttribute('aria-controls');
    await user.click(deleteButton);
    expect(deleteButton).toHaveAttribute('aria-controls', 'strategy-my-setup-confirm-delete');
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => expect(mocks.deleteStrategyAction).toHaveBeenCalled());
    expect((mocks.deleteStrategyAction.mock.calls[0][1] as FormData).get('slug')).toBe('my-setup');
    expect(screen.getByRole('alert')).toBeEmptyDOMElement();
  });

  it('announces a failed delete as an alert', async () => {
    const user = userEvent.setup();
    mocks.deleteStrategyAction.mockResolvedValue({
      status: 'error',
      message: 'The strategy database is unavailable.',
    });
    render(<StrategyActions slug="my-setup" name="My setup" builtin={false} />);

    await user.click(screen.getByRole('button', { name: 'Delete: My setup' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The strategy database is unavailable.'
    );
  });
});

describe('StrategyList', () => {
  it('lists custom strategies, then built-ins with a read-only badge', () => {
    render(
      <StrategyList strategies={[BUILTIN, makeStrategy({ mtf: true })]} catalogue={CATALOGUE} />
    );

    const custom = screen.getByRole('region', { name: 'Your strategies' });
    const builtins = screen.getByRole('region', { name: 'Built-in strategies' });
    expect(within(custom).getByRole('article', { name: 'My setup' })).toBeInTheDocument();
    expect(within(custom).queryByText('Built-in, read-only')).not.toBeInTheDocument();
    expect(within(builtins).getByText('Built-in, read-only')).toBeInTheDocument();
    expect(within(custom).getByText('Zone at most N bars old (bars 50)')).toBeInTheDocument();
    expect(within(custom).getByText('Scored, at least 1 of 2')).toBeInTheDocument();
    expect(within(builtins).getByText('None')).toBeInTheDocument();
  });

  it('says so when there are no custom strategies', () => {
    render(<StrategyList strategies={[BUILTIN]} catalogue={[]} />);

    expect(screen.getByTestId('no-custom-strategies')).toBeInTheDocument();
    // Without the catalogue, conditions show their keys.
    expect(screen.getByText('aligned')).toBeInTheDocument();
  });

  it('renders names as text, never markup', () => {
    render(
      <StrategyList
        strategies={[makeStrategy({ name: '<img src=x onerror=alert(1)>' })]}
        catalogue={CATALOGUE}
      />
    );

    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
  });
});
