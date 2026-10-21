// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeClosedEntry } from '../../helpers/journal-fixtures';

const mocks = vi.hoisted(() => ({ fetchJournal: vi.fn() }));

vi.mock('@/lib/api/journal', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/journal')>('@/lib/api/journal');
  return { ...actual, fetchJournal: mocks.fetchJournal };
});

import { GET } from '@/app/journal/export/route';
import { MAX_EXPORT_PAGES } from '@/lib/journal/csv';

const ok = (items: unknown[], next: string | null) => ({
  success: true,
  data: { items, next_cursor: next },
});

describe('GET /journal/export', () => {
  beforeEach(() => mocks.fetchJournal.mockReset());

  it('returns every page as CSV, newest first', async () => {
    mocks.fetchJournal
      .mockResolvedValueOnce(ok([makeClosedEntry({ id: 2 })], 'Y3Vy'))
      .mockResolvedValueOnce(ok([makeClosedEntry({ id: 1 })], null));

    const response = await GET();

    expect(response.status).toBe(200);
    expect(response.headers.get('Content-Type')).toBe('text/csv; charset=utf-8');
    expect(response.headers.get('Content-Disposition')).toMatch(
      /^attachment; filename="smc-journal-\d{8}T\d{6}Z\.csv"$/
    );
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(response.headers.get('X-Export-Truncated')).toBeNull();
    expect((await response.text()).trim().split('\r\n')).toHaveLength(3);
    expect(mocks.fetchJournal).toHaveBeenNthCalledWith(1, { limit: 100, cursor: undefined });
    expect(mocks.fetchJournal).toHaveBeenNthCalledWith(2, { limit: 100, cursor: 'Y3Vy' });
  });

  it('exports only the header for an empty journal', async () => {
    mocks.fetchJournal.mockResolvedValue(ok([], null));
    const response = await GET();
    expect((await response.text()).trim().split('\r\n')).toHaveLength(1);
  });

  it('stops at the page cap and says so', async () => {
    mocks.fetchJournal.mockResolvedValue(ok([makeClosedEntry()], 'Y3Vy'));
    const response = await GET();
    expect(mocks.fetchJournal).toHaveBeenCalledTimes(MAX_EXPORT_PAGES);
    expect(response.headers.get('X-Export-Truncated')).toBe('true');
  });

  it('is not truncated when the last allowed page ends the journal', async () => {
    for (let page = 1; page < MAX_EXPORT_PAGES; page += 1) {
      mocks.fetchJournal.mockResolvedValueOnce(ok([makeClosedEntry()], 'Y3Vy'));
    }
    mocks.fetchJournal.mockResolvedValueOnce(ok([makeClosedEntry()], null));

    const response = await GET();

    expect(mocks.fetchJournal).toHaveBeenCalledTimes(MAX_EXPORT_PAGES);
    expect(response.headers.get('X-Export-Truncated')).toBeNull();
  });

  it('is a plain-text 503 when the API is unreachable', async () => {
    mocks.fetchJournal.mockResolvedValue({ success: false, error: 'fixed message' });
    const response = await GET();
    expect(response.status).toBe(503);
    expect(response.headers.get('Content-Type')).toBe('text/plain; charset=utf-8');
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(await response.text()).toBe('fixed message');
  });

  it('returns an error, never a partial file, when a later page is rate limited', async () => {
    mocks.fetchJournal
      .mockResolvedValueOnce(ok([makeClosedEntry()], 'Y3Vy'))
      .mockResolvedValueOnce({ success: false, error: 'slow down', status: 429 });

    const response = await GET();

    expect(response.status).toBe(429);
    expect(response.headers.get('Content-Type')).toBe('text/plain; charset=utf-8');
    expect(await response.text()).toBe('slow down');
  });

  it('never returns a non-error status for a failure', async () => {
    mocks.fetchJournal.mockResolvedValue({ success: false, error: 'fixed', status: 200 });
    expect((await GET()).status).toBe(502);
  });
});
