/** The journal components: form states, table, row delete confirmation, pager and the Log trade link. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { makeAnalysis } from '../../helpers/fixtures';
import { makeClosedEntry, makeEntry } from '../../helpers/journal-fixtures';

const mocks = vi.hoisted(() => ({
  saveJournalAction: vi.fn(),
  deleteJournalAction: vi.fn(),
}));
vi.mock('@/app/journal/actions', () => mocks);

import { JournalForm } from '@/components/journal/journal-form';
import { JournalPager } from '@/components/journal/journal-pager';
import { JournalRowActions } from '@/components/journal/journal-row-actions';
import { JournalTable } from '@/components/journal/journal-table';
import { LogTradeButton } from '@/components/journal/log-trade-button';
import { EMPTY_JOURNAL_VALUES, type JournalFormValues } from '@/lib/journal/form';

const INITIAL: JournalFormValues = { ...EMPTY_JOURNAL_VALUES, opened_at: '2026-10-20T10:00' };

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
});

describe('JournalForm', () => {
  it('has labelled controls and starts as an add form', () => {
    render(<JournalForm initialValues={INITIAL} />);

    for (const label of [
      'Symbol',
      'Timeframe',
      'Side',
      'Entry price',
      'Stop price',
      'Exit price',
      'Size',
      'Result (currency)',
      'Opened (UTC)',
      'Closed (UTC)',
      'Notes',
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByRole('form', { name: 'New journal entry' })).toBeInTheDocument();
    expect(screen.getByLabelText('Opened (UTC)')).toHaveValue('2026-10-20T10:00');
    expect(screen.getByRole('button', { name: 'Add entry' })).toBeEnabled();
    expect(screen.queryByRole('link', { name: 'Cancel' })).not.toBeInTheDocument();
  });

  it('submits the typed values to the action', async () => {
    mocks.saveJournalAction.mockResolvedValue({ status: 'idle' });
    const user = userEvent.setup();
    render(<JournalForm initialValues={INITIAL} />);

    await user.type(screen.getByLabelText('Symbol'), 'EURUSD');
    await user.type(screen.getByLabelText('Entry price'), '1.1');
    await user.type(screen.getByLabelText('Stop price'), '1.09');
    await user.click(screen.getByRole('button', { name: 'Add entry' }));

    await waitFor(() => expect(mocks.saveJournalAction).toHaveBeenCalled());
    const data = mocks.saveJournalAction.mock.calls[0][1] as FormData;
    expect(data.get('symbol')).toBe('EURUSD');
    expect(data.get('entry')).toBe('1.1');
    expect(data.get('side')).toBe('long');
    expect(data.get('id')).toBeNull();
  });

  it('shows prefilled values, including the linked analysis', () => {
    render(
      <JournalForm
        initialValues={{
          ...INITIAL,
          symbol: 'GBPUSD',
          side: 'short',
          entry: '1.25',
          analysis_id: '9',
        }}
      />
    );

    expect(screen.getByLabelText('Symbol')).toHaveValue('GBPUSD');
    expect(screen.getByLabelText('Side')).toHaveValue('short');
    expect(screen.getByText(/analysis #9/i)).toBeInTheDocument();
  });

  it('shows each field error, marks it invalid and focuses the first one', async () => {
    mocks.saveJournalAction.mockResolvedValue({
      status: 'error',
      errors: { stop: 'For a long trade the stop must be below the entry.' },
      values: { ...INITIAL, symbol: 'EURUSD', entry: '1.1', stop: '1.2' },
    });
    const user = userEvent.setup();
    render(<JournalForm initialValues={INITIAL} />);

    await user.click(screen.getByRole('button', { name: 'Add entry' }));

    const stop = await screen.findByLabelText('Stop price');
    await waitFor(() => expect(stop).toHaveAttribute('aria-invalid', 'true'));
    expect(stop).toHaveFocus();
    expect(stop).toHaveAccessibleDescription(/stop must be below/);
    expect(stop).toHaveValue('1.2');
    expect(screen.getByLabelText('Entry price')).not.toHaveAttribute('aria-invalid');
  });

  it('announces a form-level message', async () => {
    mocks.saveJournalAction.mockResolvedValue({
      status: 'error',
      message: 'The journal database is unavailable.',
      errors: {},
      values: INITIAL,
    });
    const user = userEvent.setup();
    render(<JournalForm initialValues={INITIAL} />);

    await user.click(screen.getByRole('button', { name: 'Add entry' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('database is unavailable');
  });

  it('edits an existing entry: carries the id, says so and offers Cancel', () => {
    render(<JournalForm initialValues={INITIAL} entryId={4} />);

    expect(screen.getByRole('form', { name: 'Edit journal entry' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled();
    expect(screen.getByRole('link', { name: 'Cancel' })).toHaveAttribute('href', '/journal');
    expect(document.querySelector('input[name="id"]')).toHaveValue('4');
  });
});

describe('JournalTable', () => {
  it('shows closed trades with their R-multiple and open trades without one', () => {
    render(
      <JournalTable
        entries={[
          makeClosedEntry({ id: 1, exit: 1.12 }),
          makeClosedEntry({ id: 2, symbol: 'GBPUSD', exit: 1.095 }),
          makeEntry({ id: 3, symbol: 'USDJPY' }),
        ]}
      />
    );

    const rows = screen.getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText('+2.00R')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Closed')).toBeInTheDocument();
    expect(within(rows[1]).getByText('-0.50R')).toBeInTheDocument();
    expect(within(rows[2]).getByText('Open')).toBeInTheDocument();
    expect(within(rows[2]).queryByText(/R$/)).not.toBeInTheDocument();
    expect(within(rows[0]).getByText('2026-10-20 10:00 UTC')).toBeInTheDocument();
  });

  it('escapes user text instead of injecting markup', () => {
    const { container } = render(
      <JournalTable
        entries={[makeEntry({ symbol: '<b>x</b>', notes: '<script>alert(1)</script>' })]}
      />
    );

    expect(screen.getByText('<script>alert(1)</script>')).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
  });

  it('puts edit and delete in every row', () => {
    render(<JournalTable entries={[makeEntry({ id: 5 })]} />);
    expect(screen.getByRole('link', { name: 'Edit: EURUSD' })).toHaveAttribute(
      'href',
      '/journal/5/edit'
    );
    expect(screen.getByRole('button', { name: 'Delete: EURUSD' })).toBeInTheDocument();
  });
});

describe('JournalRowActions', () => {
  it('asks for confirmation before deleting, with Cancel focused', async () => {
    mocks.deleteJournalAction.mockResolvedValue({ status: 'success', message: 'Entry deleted.' });
    const user = userEvent.setup();
    render(<JournalRowActions entry={makeEntry({ id: 5 })} />);

    await user.click(screen.getByRole('button', { name: 'Delete: EURUSD' }));
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    expect(mocks.deleteJournalAction).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => expect(mocks.deleteJournalAction).toHaveBeenCalled());
    const data = mocks.deleteJournalAction.mock.calls[0][1] as FormData;
    expect(data.get('id')).toBe('5');
    expect(await screen.findByText('Entry deleted.')).toBeInTheDocument();
  });

  it('cancels with the button or Escape and returns focus to Delete', async () => {
    const user = userEvent.setup();
    render(<JournalRowActions entry={makeEntry()} />);
    const trigger = screen.getByRole('button', { name: 'Delete: EURUSD' });

    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('button', { name: 'Confirm delete' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('button', { name: 'Confirm delete' })).not.toBeInTheDocument();
    expect(mocks.deleteJournalAction).not.toHaveBeenCalled();
  });

  it('announces a failed delete as an alert', async () => {
    mocks.deleteJournalAction.mockResolvedValue({
      status: 'error',
      message: 'That journal entry no longer exists.',
    });
    const user = userEvent.setup();
    render(<JournalRowActions entry={makeEntry()} />);

    await user.click(screen.getByRole('button', { name: 'Delete: EURUSD' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('no longer exists');
  });

  it('moves focus to the page heading after a successful delete', async () => {
    mocks.deleteJournalAction.mockResolvedValue({ status: 'success', message: 'Entry deleted.' });
    const user = userEvent.setup();
    render(
      <>
        <h1 id="journal-heading" tabIndex={-1}>
          Journal
        </h1>
        <JournalRowActions entry={makeEntry()} />
      </>
    );

    await user.click(screen.getByRole('button', { name: 'Delete: EURUSD' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Journal' })).toHaveFocus());
  });
});

describe('JournalPager', () => {
  it('renders nothing on a single page', () => {
    const { container } = render(<JournalPager nextCursor={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('offers Load more with the cursor, and Newest after the first page', () => {
    const { rerender } = render(<JournalPager nextCursor="a b&c" />);
    expect(screen.getByRole('link', { name: 'Load more' })).toHaveAttribute(
      'href',
      '/journal?cursor=a+b%26c'
    );
    expect(screen.queryByRole('link', { name: 'Newest' })).not.toBeInTheDocument();

    rerender(<JournalPager cursor="abc" nextCursor={null} />);
    expect(screen.getByRole('link', { name: 'Newest' })).toHaveAttribute('href', '/journal');
    expect(screen.queryByRole('link', { name: 'Load more' })).not.toBeInTheDocument();
  });
});

describe('LogTradeButton', () => {
  it('links to the new-entry form prefilled from the analysis', () => {
    render(
      <LogTradeButton
        analysis={makeAnalysis({
          id: 9,
          verdict: { action: 'SELL', confidence: 60, entry: 1.25, stop: 1.26 },
        })}
      />
    );

    const href = screen.getByRole('link', { name: 'Log trade' }).getAttribute('href') ?? '';
    const url = new URL(href, 'http://x');
    expect(url.pathname).toBe('/journal/new');
    expect(url.searchParams.get('side')).toBe('short');
    expect(url.searchParams.get('entry')).toBe('1.25');
    expect(url.searchParams.get('analysis_id')).toBe('9');
  });
});
