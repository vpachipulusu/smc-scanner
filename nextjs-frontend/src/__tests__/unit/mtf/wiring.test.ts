// @vitest-environment node
/** Params, scan/analyse wire format, server action and schedule form parsing carry both flags. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULTS, parseScanParams, scanHref, scanSearchParams } from '@/lib/scan/params';
import { parseScheduleForm, valuesFromSchedule } from '@/lib/automation/form';
import { makeSchedule } from '../../helpers/automation-fixtures';

const mocks = vi.hoisted(() => ({ runAnalyse: vi.fn() }));
vi.mock('@/lib/api/analyse', () => ({ runAnalyse: mocks.runAnalyse }));

import { analyseScanAction } from '@/app/scan/actions';
import { IDLE_ANALYSE_STATE } from '@/lib/scan/analyse-state';

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

describe('scan params', () => {
  it('defaults both flags to off', () => {
    expect(DEFAULTS.mtf).toBe(false);
    expect(DEFAULTS.requireHtfAligned).toBe(false);
    expect(parseScanParams({}).query).toMatchObject({ mtf: false, requireHtfAligned: false });
  });

  it('parses mtf and htf', () => {
    expect(parseScanParams({ mtf: '1', htf: '1' }).query).toMatchObject({
      mtf: true,
      requireHtfAligned: true,
    });
    expect(parseScanParams({ mtf: 'on' }).query).toMatchObject({
      mtf: true,
      requireHtfAligned: false,
    });
  });

  it('ignores htf without mtf and junk values', () => {
    expect(parseScanParams({ htf: '1' }).query.requireHtfAligned).toBe(false);
    expect(parseScanParams({ mtf: 'maybe', htf: '1' }).query).toMatchObject({
      mtf: false,
      requireHtfAligned: false,
    });
  });

  it('serialises only what differs and round-trips', () => {
    const base = { query: DEFAULTS, every: 0 };
    expect(scanHref(base)).toBe('/scan');
    const both = { query: { ...DEFAULTS, mtf: true, requireHtfAligned: true }, every: 0 };
    expect(scanSearchParams(both).toString()).toBe('mtf=1&htf=1');
    expect(parseScanParams(Object.fromEntries(scanSearchParams(both)))).toEqual(both);
    const onlyMtf = { query: { ...DEFAULTS, mtf: true }, every: 0 };
    expect(scanSearchParams(onlyMtf).toString()).toBe('mtf=1');
  });

  it('never serialises htf without mtf', () => {
    const odd = { query: { ...DEFAULTS, requireHtfAligned: true }, every: 0 };
    expect(scanSearchParams(odd).has('htf')).toBe(false);
  });
});

describe('analyseScanAction', () => {
  beforeEach(() => {
    mocks.runAnalyse.mockReset();
    mocks.runAnalyse.mockResolvedValue({
      success: true,
      data: { source: 'mt5', tf: '1h', count: 0, rows: [], failures: [] },
    });
  });

  it('passes the carried flags to the analysis', async () => {
    await analyseScanAction(IDLE_ANALYSE_STATE, form({ mtf: '1', htf: '1' }));

    expect(mocks.runAnalyse).toHaveBeenCalledWith(
      expect.objectContaining({ mtf: true, requireHtfAligned: true })
    );
  });

  it('keeps both off by default and drops htf without mtf', async () => {
    await analyseScanAction(IDLE_ANALYSE_STATE, form({ htf: '1' }));

    expect(mocks.runAnalyse).toHaveBeenCalledWith(
      expect.objectContaining({ mtf: false, requireHtfAligned: false })
    );
  });
});

describe('schedule form', () => {
  const VALID = { name: 'A', source: 'demo', tf: '1h', symbols: 'EURUSD', frequency: '1h' };

  it('defaults both off in the body', () => {
    const parsed = parseScheduleForm(form(VALID));

    expect(parsed.ok && parsed.body).toMatchObject({ mtf: false, require_htf_aligned: false });
  });

  it('reads both checkboxes', () => {
    const parsed = parseScheduleForm(form({ ...VALID, mtf: 'on', require_htf_aligned: 'on' }));

    expect(parsed.ok && parsed.body).toMatchObject({ mtf: true, require_htf_aligned: true });
  });

  it('rejects require_htf_aligned without mtf with a field error and keeps the values', () => {
    const parsed = parseScheduleForm(form({ ...VALID, require_htf_aligned: 'on' }));

    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.errors.require_htf_aligned).toMatch(/timeframe context/i);
    expect(parsed.values.require_htf_aligned).toBe(true);
  });

  it('fills the edit form from a schedule', () => {
    expect(
      valuesFromSchedule(makeSchedule({ mtf: true, require_htf_aligned: true }))
    ).toMatchObject({
      mtf: true,
      require_htf_aligned: true,
    });
  });
});
