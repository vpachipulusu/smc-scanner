// @vitest-environment node
/** The server action re-parses the carried scan options, calls the wrapper and returns fixed state. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeAnalysedRow } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({
  runAnalyse: vi.fn(),
  /** A plain function (not a spy): vitest 5 fails a test when a spy throws, even if it is caught. */
  thrower: null as (() => Promise<never>) | null,
}));
vi.mock('@/lib/api/analyse', () => ({
  runAnalyse: (...args: unknown[]) => mocks.thrower?.() ?? mocks.runAnalyse(...args),
}));

import { analyseScanAction } from '@/app/scan/actions';
import { ANALYSE_FAILED_MESSAGE } from '@/lib/api/analyse-messages';
import { aiAvailable, IDLE_ANALYSE_STATE } from '@/lib/scan/analyse-state';

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

describe('analyseScanAction', () => {
  beforeEach(() => {
    mocks.runAnalyse.mockReset();
    mocks.thrower = null;
  });

  it('runs the analysis for the carried options and returns the rows', async () => {
    const row = makeAnalysedRow();
    mocks.runAnalyse.mockResolvedValue({
      success: true,
      data: { source: 'demo', tf: '15m', count: 1, rows: [row], failures: [] },
    });

    const state = await analyseScanAction(
      IDLE_ANALYSE_STATE,
      form({ source: 'demo', tf: '15m', symbols: 'EURUSD,XAUUSD', all: '1' })
    );

    expect(mocks.runAnalyse).toHaveBeenCalledWith({
      source: 'demo',
      tf: '15m',
      symbols: ['EURUSD', 'XAUUSD'],
      bars: 500,
      swing: 10,
      near: 0.5,
      allTouches: true,
      mtf: false,
      requireHtfAligned: false,
    });
    expect(state).toEqual({ status: 'success', rows: [row], failures: [] });
  });

  it('falls back to defaults for tampered fields and ignores files', async () => {
    mocks.runAnalyse.mockResolvedValue({
      success: true,
      data: { source: 'mt5', tf: '1h', count: 0, rows: [], failures: [] },
    });
    const data = form({ source: 'evil', bars: '-4', tf: '1h' });
    data.append('upload', new File(['x'], 'x.txt'));

    await analyseScanAction(IDLE_ANALYSE_STATE, data);

    expect(mocks.runAnalyse).toHaveBeenCalledWith(
      expect.objectContaining({ source: 'mt5', bars: 500, tf: '1h' })
    );
  });

  it('reads only the known fields, skips files under real keys and survives prototype keys', async () => {
    mocks.runAnalyse.mockResolvedValue({
      success: true,
      data: { source: 'mt5', tf: '1h', count: 0, rows: [], failures: [] },
    });
    const data = form({ __proto__: 'x', constructor: 'y', bars: '100', unknown: 'z' });
    data.append('source', new File(['x'], 'demo'));
    data.append('symbols', 'A'.repeat(5000));

    await analyseScanAction(IDLE_ANALYSE_STATE, data);

    expect(mocks.runAnalyse).toHaveBeenCalledWith(
      expect.objectContaining({ source: 'mt5', bars: 100, symbols: [] })
    );
  });

  it('returns a fixed message when the wrapper throws', async () => {
    mocks.thrower = async () => {
      throw new Error('boom sk-ant');
    };

    const out = await analyseScanAction(IDLE_ANALYSE_STATE, form({}));

    expect(out).toEqual({
      status: 'error',
      message: ANALYSE_FAILED_MESSAGE,
    });
  });

  it('keeps the first value of a repeated field', async () => {
    mocks.runAnalyse.mockResolvedValue({
      success: true,
      data: { source: 'demo', tf: '1h', count: 0, rows: [], failures: [] },
    });
    const data = form({ source: 'demo' });
    data.append('source', 'mt5');

    await analyseScanAction(IDLE_ANALYSE_STATE, data);

    expect(mocks.runAnalyse).toHaveBeenCalledWith(expect.objectContaining({ source: 'demo' }));
  });

  it('returns the wrapper message when the analysis fails', async () => {
    mocks.runAnalyse.mockResolvedValue({ success: false, error: 'Fixed text', status: 429 });

    expect(await analyseScanAction(IDLE_ANALYSE_STATE, form({}))).toEqual({
      status: 'error',
      message: 'Fixed text',
    });
  });
});

describe('aiAvailable', () => {
  it('is true without a flag or without config', () => {
    expect(aiAvailable(null)).toBe(true);
    expect(aiAvailable({} as never)).toBe(true);
  });

  it('is false only when the API says the key is missing', () => {
    expect(aiAvailable({ ai_enabled: false } as never)).toBe(false);
    expect(aiAvailable({ ai_enabled: true } as never)).toBe(true);
    expect(aiAvailable({ ai_enabled: 'no' } as never)).toBe(true);
  });
});
