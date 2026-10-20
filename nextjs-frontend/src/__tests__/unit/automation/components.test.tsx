/** The automation components: form states, row actions with delete confirmation, and safe log rendering. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { makeLog, makeSchedule } from '../../helpers/automation-fixtures';

const mocks = vi.hoisted(() => ({
  saveScheduleAction: vi.fn(),
  toggleScheduleAction: vi.fn(),
  runScheduleAction: vi.fn(),
  deleteScheduleAction: vi.fn(),
}));
vi.mock('@/app/automation/actions', () => mocks);

import { JobLogTable } from '@/components/automation/job-log-table';
import { ScheduleActions } from '@/components/automation/schedule-actions';
import { ScheduleForm } from '@/components/automation/schedule-form';
import { SchedulesTable } from '@/components/automation/schedules-table';

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
});

describe('ScheduleForm', () => {
  it('has labelled, keyboard-reachable controls', () => {
    render(<ScheduleForm />);

    for (const label of [
      'Name',
      'Source',
      'Timeframe',
      'Symbols',
      'Frequency',
      'Min score',
      'Min confidence',
      'Telegram chat id',
      'Only on change',
      'Send HOLD verdicts',
      'Enabled',
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Create schedule' })).toBeEnabled();
    expect(screen.getByLabelText('Enabled')).toBeChecked();
    expect(screen.queryByRole('link', { name: 'Cancel' })).not.toBeInTheDocument();
  });

  it('submits the typed values to the action', async () => {
    mocks.saveScheduleAction.mockResolvedValue({
      status: 'success',
      message: 'Schedule "A" created.',
    });
    const user = userEvent.setup();
    render(<ScheduleForm />);

    await user.type(screen.getByLabelText('Name'), 'A');
    await user.type(screen.getByLabelText('Symbols'), 'EURUSD');
    await user.click(screen.getByRole('button', { name: 'Create schedule' }));

    await waitFor(() => expect(mocks.saveScheduleAction).toHaveBeenCalled());
    const data = mocks.saveScheduleAction.mock.calls[0][1] as FormData;
    expect(data.get('name')).toBe('A');
    expect(data.get('symbols')).toBe('EURUSD');
    expect(data.get('enabled')).toBe('on');
    expect(await screen.findByRole('status')).toHaveTextContent('Schedule "A" created.');
  });

  it('shows each field error next to its field and keeps the typed values', async () => {
    mocks.saveScheduleAction.mockResolvedValue({
      status: 'error',
      errors: { name: 'Enter a name.', symbols: 'Enter at least one symbol.' },
      values: {
        name: '',
        source: 'demo',
        tf: '1h',
        symbols: '',
        frequency: '1h',
        min_score: '9',
        min_confidence: '0',
        only_on_change: true,
        send_hold: false,
        enabled: false,
        telegram_chat_id: '',
      },
    });
    const user = userEvent.setup();
    render(<ScheduleForm />);

    await user.click(screen.getByRole('button', { name: 'Create schedule' }));

    const name = await screen.findByLabelText('Name');
    await waitFor(() => expect(name).toHaveAttribute('aria-invalid', 'true'));
    expect(name).toHaveAccessibleDescription('Enter a name.');
    expect(screen.getByLabelText('Symbols')).toHaveAccessibleDescription(
      /Enter at least one symbol\./
    );
    expect(screen.getByLabelText('Source')).not.toHaveAttribute('aria-invalid');
    expect(screen.getByLabelText('Min score')).toHaveValue(9);
    expect(screen.getByLabelText('Only on change')).toBeChecked();
    expect(screen.getByLabelText('Enabled')).not.toBeChecked();
  });

  it('shows a request-level error as an alert', async () => {
    mocks.saveScheduleAction.mockResolvedValue({
      status: 'error',
      message: 'The scanner API could not be reached.',
      errors: {},
      values: {
        name: 'A',
        source: 'demo',
        tf: '1h',
        symbols: 'EURUSD',
        frequency: '1h',
        min_score: '2',
        min_confidence: '0',
        only_on_change: false,
        send_hold: false,
        enabled: true,
        telegram_chat_id: '',
      },
    });
    const user = userEvent.setup();
    render(<ScheduleForm />);

    await user.click(screen.getByRole('button', { name: 'Create schedule' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('could not be reached');
  });

  it('prefills an edited schedule, carries its id and offers Cancel', () => {
    render(
      <ScheduleForm schedule={makeSchedule({ id: 8, name: 'Edit me', symbols: ['A', 'B'] })} />
    );

    expect(screen.getByLabelText('Name')).toHaveValue('Edit me');
    expect(screen.getByLabelText('Symbols')).toHaveValue('A, B');
    expect(document.querySelector('input[name="id"]')).toHaveValue('8');
    expect(screen.getByRole('link', { name: 'Cancel' })).toHaveAttribute('href', '/automation');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeInTheDocument();
  });
});

describe('ScheduleActions', () => {
  it('toggles the schedule with the next state', async () => {
    mocks.toggleScheduleAction.mockResolvedValue({
      status: 'success',
      message: 'Schedule disabled.',
    });
    const user = userEvent.setup();
    render(<ScheduleActions schedule={makeSchedule({ id: 4, enabled: true })} />);

    await user.click(screen.getByRole('button', { name: 'Disable: Morning scan' }));

    await waitFor(() => expect(mocks.toggleScheduleAction).toHaveBeenCalled());
    const data = mocks.toggleScheduleAction.mock.calls[0][1] as FormData;
    expect([data.get('id'), data.get('enabled')]).toEqual(['4', 'false']);
    expect(await screen.findByRole('status')).toHaveTextContent('Schedule disabled.');
  });

  it('offers Enable for a disabled schedule', () => {
    render(<ScheduleActions schedule={makeSchedule({ enabled: false })} />);
    expect(screen.getByRole('button', { name: 'Enable: Morning scan' })).toHaveTextContent(
      'Enable'
    );
  });

  it('runs now and shows the busy message from a 409', async () => {
    mocks.runScheduleAction.mockResolvedValue({
      status: 'error',
      message: 'A run is already in progress. Try again when it finishes.',
    });
    const user = userEvent.setup();
    render(<ScheduleActions schedule={makeSchedule({ id: 4 })} />);

    await user.click(screen.getByRole('button', { name: 'Run now: Morning scan' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('already in progress');
  });

  it('links to the logs and the edit form', () => {
    render(<ScheduleActions schedule={makeSchedule({ id: 4 })} />);

    expect(screen.getByRole('link', { name: 'Logs: Morning scan' })).toHaveAttribute(
      'href',
      '/automation/4/logs'
    );
    expect(screen.getByRole('link', { name: 'Edit: Morning scan' })).toHaveAttribute(
      'href',
      '/automation?edit=4'
    );
  });

  it('asks for confirmation before deleting and can be cancelled', async () => {
    const user = userEvent.setup();
    render(<ScheduleActions schedule={makeSchedule({ id: 4 })} />);

    await user.click(screen.getByRole('button', { name: 'Delete: Morning scan' }));
    expect(mocks.deleteScheduleAction).not.toHaveBeenCalled();
    expect(screen.getByRole('form', { name: 'Confirm delete: Morning scan' })).toBeInTheDocument();
    // Cancel, not the destructive button, has the initial focus.
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('form', { name: /Confirm delete/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete: Morning scan' })).toHaveFocus();
    expect(mocks.deleteScheduleAction).not.toHaveBeenCalled();
  });

  it('deletes only after the confirmation is pressed', async () => {
    mocks.deleteScheduleAction.mockResolvedValue({
      status: 'success',
      message: 'Schedule deleted.',
    });
    const user = userEvent.setup();
    render(<ScheduleActions schedule={makeSchedule({ id: 4 })} />);

    await user.click(screen.getByRole('button', { name: 'Delete: Morning scan' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => expect(mocks.deleteScheduleAction).toHaveBeenCalledTimes(1));
    expect((mocks.deleteScheduleAction.mock.calls[0][1] as FormData).get('id')).toBe('4');
    expect(await screen.findByRole('status')).toHaveTextContent('Schedule deleted.');
  });
});

describe('SchedulesTable', () => {
  it('shows status, scan summary, last and next run', () => {
    render(
      <SchedulesTable
        schedules={[
          makeSchedule({ id: 1, name: 'On', symbols: ['EURUSD', 'XAUUSD'] }),
          makeSchedule({ id: 2, name: 'Off', enabled: false, last_run_at: null }),
        ]}
      />
    );

    expect(screen.getByRole('table', { name: 'Schedules' })).toBeInTheDocument();
    expect(screen.getByText('Enabled')).toBeInTheDocument();
    expect(screen.getByText('Disabled')).toBeInTheDocument();
    expect(screen.getByText(/EURUSD, XAUUSD/)).toBeInTheDocument();
    expect(screen.getByText('2026-10-20 15:03 UTC')).toBeInTheDocument();
  });

  it('renders a hostile name as text, not markup', () => {
    render(<SchedulesTable schedules={[makeSchedule({ name: '<img src=x onerror=alert(1)>' })]} />);

    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
  });
});

describe('JobLogTable', () => {
  it('shows status, duration, hits, delivered and the skip reason', () => {
    render(
      <JobLogTable
        logs={[
          makeLog({ id: 1 }),
          makeLog({ id: 2, status: 'skipped', skip_reason: 'No change since last run', hits: 0 }),
        ]}
      />
    );

    expect(screen.getByText('Success')).toBeInTheDocument();
    expect(screen.getByText('Skipped')).toBeInTheDocument();
    expect(screen.getAllByText('2.3 s')).toHaveLength(2);
    expect(screen.getByText('Skipped: No change since last run')).toBeInTheDocument();
  });

  it('shows only the first line of an error, never the stack trace', () => {
    render(
      <JobLogTable
        logs={[
          makeLog({
            status: 'failed',
            error:
              'LoaderError: unknown symbol\nTraceback (most recent call last):\n  File "/srv/app.py", line 3',
          }),
        ]}
      />
    );

    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Error: LoaderError: unknown symbol')).toBeInTheDocument();
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument();
    expect(screen.queryByText(/app\.py/)).not.toBeInTheDocument();
  });

  it('renders markup in skip reasons and errors as escaped text', () => {
    render(
      <JobLogTable
        logs={[
          makeLog({
            status: 'failed',
            skip_reason: '<script>window.__x=1</script>',
            error: '<img src=x onerror="window.__y=1">',
          }),
        ]}
      />
    );

    expect(screen.getByText('Skipped: <script>window.__x=1</script>')).toBeInTheDocument();
    expect(screen.getByText('Error: <img src=x onerror="window.__y=1">')).toBeInTheDocument();
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('img')).toBeNull();
  });

  it('shows a dash when there is nothing to say', () => {
    render(<JobLogTable logs={[makeLog()]} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('accessibility behaviours', () => {
  it('cancels the delete confirmation with Escape and returns focus to Delete', async () => {
    const user = userEvent.setup();
    render(<ScheduleActions schedule={makeSchedule()} />);

    await user.click(screen.getByRole('button', { name: 'Delete: Morning scan' }));
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('form', { name: /Confirm delete/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete: Morning scan' })).toHaveFocus();
  });

  it('moves focus to the page heading after a delete succeeds', async () => {
    mocks.deleteScheduleAction.mockResolvedValue({
      status: 'success',
      message: 'Schedule deleted.',
    });
    const user = userEvent.setup();
    render(
      <>
        <h1 id="automation-heading" tabIndex={-1}>
          Automation
        </h1>
        <ScheduleActions schedule={makeSchedule()} />
      </>
    );

    await user.click(screen.getByRole('button', { name: 'Delete: Morning scan' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Automation' })).toHaveFocus());
  });

  it('focuses the first invalid field after a failed submit', async () => {
    mocks.saveScheduleAction.mockResolvedValue({
      status: 'error',
      errors: { symbols: 'Enter at least one symbol.' },
      values: {
        name: 'A',
        source: 'demo',
        tf: '1h',
        symbols: '',
        frequency: '1h',
        min_score: '2',
        min_confidence: '0',
        only_on_change: false,
        send_hold: false,
        enabled: true,
        telegram_chat_id: '',
      },
    });
    const user = userEvent.setup();
    render(<ScheduleForm />);

    await user.click(screen.getByRole('button', { name: 'Create schedule' }));

    await waitFor(() => expect(screen.getByLabelText('Symbols')).toHaveFocus());
  });

  it('focuses the name field when editing and describes fields with their hints', () => {
    render(<ScheduleForm schedule={makeSchedule()} />);

    expect(screen.getByLabelText('Name')).toHaveFocus();
    expect(screen.getByLabelText('Symbols')).toHaveAccessibleDescription(/commas or spaces/);
    expect(screen.getByLabelText('Telegram chat id')).toHaveAccessibleDescription(/@channelname/);
  });
});
