/** Strategy in the URL, deep-link tuning, the picker's choices, condition chips and the schedule form. */
import { describe, expect, it } from 'vitest';
import { parseScheduleForm, readValues, valuesFromSchedule } from '@/lib/automation/form';
import {
  checkedConditions,
  conditionChips,
  conditionLabels,
  fallbackLabel,
} from '@/lib/scan/conditions';
import { csvFileName } from '@/lib/scan/csv';
import {
  DEFAULTS,
  hasParam,
  parseScanParams,
  scanHref,
  withStrategyTuning,
} from '@/lib/scan/params';
import {
  findStrategy,
  isMissingStrategy,
  strategyName,
  strategyOptions,
} from '@/lib/scan/strategy-options';
import { makeSchedule } from '../../helpers/automation-fixtures';
import { OPTIONS, makeStrategy } from '../../helpers/strategy-fixtures';

const SUMMARY = {
  slug: 'fresh-ob-trend',
  name: 'Fresh OB',
  builtin: true,
  swing_length: 7,
  near_atr: 0.3,
};

describe('strategy search param', () => {
  it('defaults to smc-default and reads a valid slug', () => {
    expect(parseScanParams({}).query.strategy).toBe('smc-default');
    expect(parseScanParams({ strategy: 'fresh-ob-trend' }).query.strategy).toBe('fresh-ob-trend');
    expect(parseScanParams({ strategy: ['my-1', 'other'] }).query.strategy).toBe('my-1');
  });

  it.each(['Bad', '-lead', 'a'.repeat(33), 'a_b', '../x', ''])(
    'falls back to the default for %j',
    (slug) => {
      expect(parseScanParams({ strategy: slug }).query.strategy).toBe('smc-default');
    }
  );

  it('keeps the default strategy out of the URL', () => {
    expect(scanHref({ query: DEFAULTS, every: 0 })).toBe('/scan');
  });

  it('writes a custom strategy with explicit swing and near so the page does not refill them', () => {
    const params = { query: { ...DEFAULTS, strategy: 'fresh-ob-trend' }, every: 0 };

    expect(scanHref(params)).toBe('/scan?strategy=fresh-ob-trend&swing=10&near=0.5');
    expect(
      parseScanParams(Object.fromEntries(new URL(scanHref(params), 'http://x').searchParams))
    ).toEqual(params);
  });
});

describe('withStrategyTuning', () => {
  const TUNING = { swingLength: 7, nearAtr: 0.3 };
  const deepLink = { strategy: 'fresh-ob-trend' };

  it('fills absent swing and near from the strategy', () => {
    const params = withStrategyTuning(parseScanParams(deepLink), deepLink, TUNING);
    expect(params.query).toMatchObject({ strategy: 'fresh-ob-trend', swing: 7, near: 0.3 });
  });

  it('keeps the values the URL set', () => {
    const raw = { ...deepLink, swing: '12', near: '' };
    const params = withStrategyTuning(parseScanParams(raw), raw, TUNING);

    expect(params.query).toMatchObject({ swing: 12, near: 0.3 });
    expect(hasParam(raw, 'swing')).toBe(true);
    expect(hasParam(raw, 'near')).toBe(false);
  });

  it('changes nothing for an unknown strategy and validates the summary values', () => {
    const parsed = parseScanParams(deepLink);
    expect(withStrategyTuning(parsed, deepLink, undefined)).toBe(parsed);
    const wild = withStrategyTuning(parsed, deepLink, { swingLength: 999, nearAtr: -1 });
    expect(wild.query).toMatchObject({ swing: DEFAULTS.swing, near: DEFAULTS.near });
  });
});

describe('csvFileName', () => {
  const at = new Date('2026-10-20T14:03:05.123Z');

  it('names a non-default strategy only', () => {
    expect(csvFileName('demo', '1h', at)).toBe('smc-scan-demo-1h-20261020T140305Z.csv');
    expect(csvFileName('demo', '1h', at, 'smc-default')).toBe(
      'smc-scan-demo-1h-20261020T140305Z.csv'
    );
    expect(csvFileName('demo', '1h', at, 'fresh-ob-trend')).toBe(
      'smc-scan-demo-1h-fresh-ob-trend-20261020T140305Z.csv'
    );
  });
});

describe('strategyOptions', () => {
  it('uses the /config summaries with mtf from the full list', () => {
    const options = strategyOptions(
      { strategies: [SUMMARY, { ...SUMMARY, slug: 'mine', builtin: false }] },
      [makeStrategy({ slug: 'fresh-ob-trend', mtf: true })]
    );

    expect(options).toEqual([
      {
        slug: 'fresh-ob-trend',
        name: 'Fresh OB',
        builtin: true,
        swingLength: 7,
        nearAtr: 0.3,
        mtf: true,
      },
      { slug: 'mine', name: 'Fresh OB', builtin: false, swingLength: 7, nearAtr: 0.3, mtf: false },
    ]);
  });

  it('falls back to the full list, and drops malformed or duplicate entries', () => {
    expect(strategyOptions(null, [makeStrategy({ mtf: true })])).toEqual([
      {
        slug: 'smc-default',
        name: 'SMC default',
        builtin: true,
        swingLength: 10,
        nearAtr: 0.5,
        mtf: true,
      },
    ]);
    const options = strategyOptions(
      {
        strategies: [
          SUMMARY,
          SUMMARY,
          { ...SUMMARY, slug: 'Bad slug' },
          { ...SUMMARY, slug: 'nan', swing_length: Number.NaN },
        ],
      },
      null
    );
    expect(options.map((option) => option.slug)).toEqual(['fresh-ob-trend']);
    expect(strategyOptions(null, null)).toEqual([]);
    const notAList = { strategies: 'oops' } as unknown as Parameters<typeof strategyOptions>[0];
    expect(strategyOptions(notAList, null)).toEqual([]);
    expect(
      strategyOptions({ strategies: [null, { ...SUMMARY, name: 'n'.repeat(101) }] } as never, null)
    ).toEqual([]);
  });

  it('finds, names and flags strategies', () => {
    expect(findStrategy(OPTIONS, 'my-setup')?.name).toBe('My setup');
    expect(strategyName(OPTIONS, 'my-setup')).toBe('My setup');
    expect(strategyName(OPTIONS, 'gone')).toBe('gone');
    const known = new Set(['smc-default', 'my-setup']);
    expect(isMissingStrategy(known, 'gone')).toBe(true);
    expect(isMissingStrategy(known, 'my-setup')).toBe(false);
    expect(isMissingStrategy(new Set(), 'smc-default')).toBe(false);
    expect(isMissingStrategy(null, 'gone')).toBe(false);
  });
});

describe('condition chips', () => {
  const labels = conditionLabels([
    { key: 'aligned', label: 'Aligned with bias' },
    { key: 'fresh', label: 'Fresh zone' },
  ]);

  it('makes one chip per condition with the catalogue label', () => {
    expect(conditionChips({ aligned: true, fresh: false, max_zone_age: true }, labels)).toEqual([
      { key: 'aligned', label: 'Aligned with bias', met: true },
      { key: 'fresh', label: 'Fresh zone', met: false },
      { key: 'max_zone_age', label: 'Max zone age', met: true },
    ]);
  });

  it('drops malformed keys and values', () => {
    expect(
      checkedConditions({ ok: true, '<b>x</b>': true, __proto__x: false, note: 'yes', n: 1 })
    ).toEqual({ ok: true });
    expect(conditionChips(undefined)).toEqual([]);
    expect(conditionLabels(undefined)).toEqual({});
    expect(conditionLabels('nope')).toEqual({});
    expect(
      conditionLabels([null, { key: 'Bad Key', label: 'x' }, { key: 'ok', label: 'y'.repeat(80) }])
    ).toEqual({ ok: 'y'.repeat(64) });
    expect(fallbackLabel('htf_aligned')).toBe('Htf aligned');
  });

  it('does not take labels from the prototype', () => {
    expect(conditionChips({ constructor: true }, {})).toEqual([
      { key: 'constructor', label: 'Constructor', met: true },
    ]);
  });
});

describe('schedule form strategy', () => {
  const form = (values: Record<string, string>) => {
    const data = new FormData();
    for (const [key, value] of Object.entries(values)) data.set(key, value);
    return data;
  };
  const VALID = { name: 'n', source: 'demo', tf: '1h', symbols: 'EURUSD', frequency: '1h' };

  it('sends the picked strategy, defaulting a blank one', () => {
    const picked = parseScheduleForm(form({ ...VALID, strategy: 'fresh-ob-trend' }));
    expect(picked.ok && picked.body.strategy).toBe('fresh-ob-trend');
    const blank = parseScheduleForm(form(VALID));
    expect(blank.ok && blank.body.strategy).toBe('smc-default');
  });

  it('rejects a malformed slug with a field error', () => {
    const parsed = parseScheduleForm(form({ ...VALID, strategy: 'Not A Slug' }));
    expect(parsed.ok).toBe(false);
    expect(!parsed.ok && parsed.errors.strategy).toBe('Choose a strategy.');
    expect(readValues(form({ strategy: 'x' })).strategy).toBe('x');
  });

  it('prefills from the schedule, older schedules reading as the default', () => {
    expect(valuesFromSchedule(makeSchedule({ strategy: 'my-setup' })).strategy).toBe('my-setup');
    expect(valuesFromSchedule(makeSchedule()).strategy).toBe('smc-default');
  });
});
