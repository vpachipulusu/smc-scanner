// @vitest-environment node
/** The automation pages read live data, validate route input and show only the fixed error messages. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { makeLog, makeSchedule } from '../../helpers/automation-fixtures';

const mocks = vi.hoisted(() => ({
  fetchSchedules: vi.fn(),
  fetchScheduleLogs: vi.fn(),
  notFound: vi.fn(),
}));
vi.mock('@/lib/api/schedules', () => ({
  fetchSchedules: mocks.fetchSchedules,
  fetchScheduleLogs: mocks.fetchScheduleLogs,
}));
vi.mock('next/navigation', () => ({ notFound: mocks.notFound }));
vi.mock('@/app/automation/actions', () => ({
  saveScheduleAction: vi.fn(),
  toggleScheduleAction: vi.fn(),
  runScheduleAction: vi.fn(),
  deleteScheduleAction: vi.fn(),
}));

import AutomationPage from '@/app/automation/page';
import AutomationLoading from '@/app/automation/loading';
import JobLogsPage from '@/app/automation/[id]/logs/page';
import { SCHEDULES_UNAVAILABLE_MESSAGE } from '@/lib/api/schedules-messages';

class NotFoundSignal extends Error {}

const automation = (edit?: string) =>
  AutomationPage({ searchParams: Promise.resolve(edit === undefined ? {} : { edit }) });
const logs = (id: string, cursor?: string) =>
  JobLogsPage({
    params: Promise.resolve({ id }),
    searchParams: Promise.resolve(cursor === undefined ? {} : { cursor }),
  });

beforeEach(() => {
  mocks.fetchSchedules.mockReset();
  mocks.fetchScheduleLogs.mockReset();
  mocks.notFound.mockReset();
  mocks.notFound.mockImplementation(() => {
    throw new NotFoundSignal('NEXT_NOT_FOUND');
  });
});

describe('AutomationPage', () => {
  it('lists schedules above an empty new-schedule form', async () => {
    mocks.fetchSchedules.mockResolvedValue({ success: true, data: [makeSchedule()] });

    const html = renderToStaticMarkup(await automation());

    expect(html).toContain('Morning scan');
    expect(html).toContain('New schedule');
    expect(html).not.toContain('Save changes');
  });

  it('says so when there are no schedules', async () => {
    mocks.fetchSchedules.mockResolvedValue({ success: true, data: [] });

    const html = renderToStaticMarkup(await automation());

    expect(html).toContain('No schedules yet');
  });

  it('shows the edit form for ?edit=id', async () => {
    mocks.fetchSchedules.mockResolvedValue({
      success: true,
      data: [makeSchedule({ id: 3, name: 'Third' })],
    });

    const html = renderToStaticMarkup(await automation('3'));

    expect(html).toContain('Edit “Third”');
    expect(html).toContain('Save changes');
  });

  it('warns and falls back to the new form when the edited schedule is gone', async () => {
    mocks.fetchSchedules.mockResolvedValue({ success: true, data: [makeSchedule()] });

    const html = renderToStaticMarkup(await automation('99'));

    expect(html).toContain('That schedule no longer exists.');
    expect(html).toContain('New schedule');
  });

  it('ignores a malformed edit id', async () => {
    mocks.fetchSchedules.mockResolvedValue({ success: true, data: [makeSchedule()] });

    const html = renderToStaticMarkup(await automation('abc'));

    expect(html).toContain('That schedule no longer exists.');
    expect(html).not.toContain('Save changes');
  });

  it('shows the fixed error and a retry link when the list cannot load', async () => {
    mocks.fetchSchedules.mockResolvedValue({
      success: false,
      error: SCHEDULES_UNAVAILABLE_MESSAGE,
    });

    const html = renderToStaticMarkup(await automation());

    expect(html).toContain(SCHEDULES_UNAVAILABLE_MESSAGE);
    expect(html).toContain('Retry');
    expect(html).not.toContain('New schedule');
  });

  it('has a loading state', () => {
    expect(renderToStaticMarkup(<AutomationLoading />)).toContain('aria-busy="true"');
  });
});

describe('JobLogsPage', () => {
  it('renders the log rows and an Older runs link carrying the cursor', async () => {
    mocks.fetchScheduleLogs.mockResolvedValue({
      success: true,
      data: { items: [makeLog({ skip_reason: 'No change' })], next_cursor: 'a b&c' },
    });

    const html = renderToStaticMarkup(await logs('1', 'start'));

    expect(mocks.fetchScheduleLogs).toHaveBeenCalledWith(1, { limit: 50, cursor: 'start' });
    expect(html).toContain('Skipped: No change');
    expect(html).toContain('/automation/1/logs?cursor=a%20b%26c');
  });

  it('says so when there are no runs and shows no Older runs link', async () => {
    mocks.fetchScheduleLogs.mockResolvedValue({
      success: true,
      data: { items: [], next_cursor: null },
    });

    const html = renderToStaticMarkup(await logs('1'));

    expect(html).toContain('No runs recorded yet.');
    expect(html).not.toContain('Older runs');
  });

  it('drops an over-long cursor instead of forwarding it', async () => {
    mocks.fetchScheduleLogs.mockResolvedValue({
      success: true,
      data: { items: [], next_cursor: null },
    });

    await logs('1', 'x'.repeat(65));

    expect(mocks.fetchScheduleLogs).toHaveBeenCalledWith(1, { limit: 50, cursor: undefined });
  });

  it.each(['abc', '0', '-3', '1.5'])('calls notFound without fetching for id %s', async (id) => {
    await expect(logs(id)).rejects.toBeInstanceOf(NotFoundSignal);
    expect(mocks.fetchScheduleLogs).not.toHaveBeenCalled();
  });

  it('calls notFound when the API says 404', async () => {
    mocks.fetchScheduleLogs.mockResolvedValue({ success: false, error: 'x', status: 404 });

    await expect(logs('9')).rejects.toBeInstanceOf(NotFoundSignal);
  });

  it('shows the fixed message and a retry link for other failures', async () => {
    mocks.fetchScheduleLogs.mockResolvedValue({
      success: false,
      error: SCHEDULES_UNAVAILABLE_MESSAGE,
    });

    const html = renderToStaticMarkup(await logs('2'));

    expect(html).toContain(SCHEDULES_UNAVAILABLE_MESSAGE);
    expect(html).toContain('/automation/2/logs');
  });
});
