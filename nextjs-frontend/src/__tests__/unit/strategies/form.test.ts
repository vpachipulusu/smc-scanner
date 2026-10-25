/** The strategy form: catalogue parsing, prefill, copy slugs and allow-listed validation. */
import { describe, expect, it } from 'vitest';

import { countModes, lowerMinScore, minScoreProblem } from '@/lib/strategies/builder';
import { conditionLabel, paramFieldsFromSchema, toConditionInfo } from '@/lib/strategies/catalogue';
import { describeCondition, describeScoring, describeTuning } from '@/lib/strategies/format';
import {
  copyName,
  copySlug,
  duplicateValues,
  emptyFormValues,
  parseParam,
  parseStrategyForm,
  readFormValues,
  valuesFromStrategy,
} from '@/lib/strategies/form';
import {
  BUILTIN,
  CATALOGUE,
  VALID_FORM,
  formOf,
  makeStrategy,
} from '../../helpers/strategies-page-fixtures';

const parse = (
  patch: Record<string, string | readonly string[]> = {},
  mode: 'create' | 'edit' = 'create'
) => parseStrategyForm(formOf({ ...VALID_FORM, ...patch }), CATALOGUE, mode);

const errorsOf = (result: ReturnType<typeof parse>) => (result.ok ? {} : result.errors);

describe('catalogue', () => {
  it('reads every params kind from params_schema', () => {
    const fields = paramFieldsFromSchema({
      properties: {
        bars: { type: 'integer', minimum: 1, maximum: 5000, title: 'Bars', default: 20 },
        atr: { type: 'number' },
        kind: { enum: ['FVG', 'OB'], default: 'OB' },
        on: { type: 'boolean', default: true },
        tag: { type: 'string', default: 'x' },
      },
      required: ['bars'],
    });
    expect(fields).toEqual([
      {
        name: 'bars',
        label: 'Bars',
        required: true,
        kind: 'integer',
        min: 1,
        max: 5000,
        defaultValue: 20,
      },
      {
        name: 'atr',
        label: 'atr',
        required: false,
        kind: 'number',
        min: undefined,
        max: undefined,
        defaultValue: undefined,
      },
      {
        name: 'kind',
        label: 'kind',
        required: false,
        kind: 'enum',
        options: ['FVG', 'OB'],
        defaultValue: 'OB',
      },
      { name: 'on', label: 'on', required: false, kind: 'boolean', defaultValue: true },
      { name: 'tag', label: 'tag', required: false, kind: 'string', defaultValue: 'x' },
    ]);
  });

  it.each([
    ['not an object', 'x'],
    ['properties not an object', { properties: [] }],
    ['an object param', { properties: { a: { type: 'object' } } }],
    ['a bad param name', { properties: { 'A-b': { type: 'integer' } } }],
    ['an empty enum', { properties: { a: { enum: [] } } }],
    ['a non-string enum', { properties: { a: { enum: [1] } } }],
    ['a non-object property', { properties: { a: 3 } }],
  ])('rejects a schema with %s', (_label, schema) => {
    expect(paramFieldsFromSchema(schema)).toBeNull();
  });

  it('accepts a schema without properties', () => {
    expect(paramFieldsFromSchema({ type: 'object' })).toEqual([]);
  });

  it('rejects too many params', () => {
    const properties = Object.fromEntries(
      Array.from({ length: 9 }, (_, i) => [`p${i}`, { type: 'integer' }])
    );
    expect(paramFieldsFromSchema({ properties })).toBeNull();
  });

  it.each([
    ['not an object', null],
    ['a bad key', { key: 'Bad', label: 'x', params_schema: {} }],
    ['no label', { key: 'ok', label: ' ', params_schema: {} }],
    ['a bad schema', { key: 'ok', label: 'x', params_schema: null }],
  ])('rejects a condition with %s', (_label, raw) => {
    expect(toConditionInfo(raw)).toBeNull();
  });

  it('labels a key, or falls back to the key', () => {
    expect(conditionLabel(CATALOGUE, 'fresh')).toBe('First touch only');
    expect(conditionLabel(CATALOGUE, 'retired')).toBe('retired');
  });
});

describe('prefill', () => {
  it('starts empty with defaults and the first enum option', () => {
    const values = emptyFormValues(CATALOGUE);
    expect(values).toMatchObject({
      swing_length: '10',
      near_atr: '0.5',
      min_score: '0',
      zone_kinds: ['FVG', 'OB'],
    });
    expect(values.conditions.zone_kind).toEqual({ mode: 'off', params: { kind: 'FVG' } });
    expect(values.conditions.max_zone_age).toEqual({ mode: 'off', params: { bars: '' } });
  });

  it('reads a strategy into modes and params', () => {
    const values = valuesFromStrategy(makeStrategy(), CATALOGUE);
    expect(values.conditions.fresh.mode).toBe('require');
    expect(values.conditions.max_zone_age).toEqual({ mode: 'score', params: { bars: '50' } });
    expect(values.conditions.in_ote.mode).toBe('off');
  });

  it('duplicates with a free slug and a copy name', () => {
    const values = duplicateValues(
      BUILTIN,
      CATALOGUE,
      new Set(['smc-default', 'smc-default-copy'])
    );
    expect(values.slug).toBe('smc-default-copy-2');
    expect(values.name).toBe('SMC default (copy)');
    expect(values.conditions.in_ote.mode).toBe('score');
  });

  it('keeps copy slugs and names within the limits', () => {
    const long = 'a'.repeat(31) + 'b';
    expect(copySlug(long, new Set())).toHaveLength(32);
    expect(copySlug('ab-----------------------------x', new Set())).toBe('ab-copy');
    expect(copyName('n'.repeat(64))).toHaveLength(64);
    const taken = new Set(
      Array.from({ length: 50 }, (_, i) => (i === 0 ? 'x-copy' : `x-copy-${i + 1}`))
    );
    expect(copySlug('x', taken)).toBe('');
  });
});

describe('parseParam', () => {
  const bars = CATALOGUE[3].params[0];
  const atr = CATALOGUE[4].params[0];
  const kind = CATALOGUE[5].params[0];

  it('checks numbers against the schema bounds', () => {
    expect(parseParam(bars, '50')).toEqual({ value: 50 });
    expect(parseParam(bars, '0').error).toBe('Enter a whole number from 1 to 5000.');
    expect(parseParam(bars, '1.5').error).toBeDefined();
    expect(parseParam(atr, '1.25')).toEqual({ value: 1.25 });
    expect(parseParam(atr, '6').error).toBe('Enter a number from 0 to 5.');
    expect(parseParam(bars, '').error).toBe('Enter a value.');
  });

  it('leaves optional params unset instead of inventing values', () => {
    const optionalEnum = {
      name: 'k',
      label: 'k',
      required: false,
      kind: 'enum' as const,
      options: ['A', 'B'],
    };
    const optionalFlag = { name: 'f', label: 'f', required: false, kind: 'boolean' as const };
    expect(parseParam(optionalEnum, '')).toEqual({});
    expect(parseParam(optionalFlag, 'false')).toEqual({});
    expect(parseParam({ ...optionalFlag, defaultValue: true }, 'false')).toEqual({ value: false });
    expect(parseParam({ ...optionalFlag, required: true }, 'false')).toEqual({ value: false });
    const catalogue = [{ key: 'c', label: 'C', params: [optionalEnum] }];
    expect(emptyFormValues(catalogue).conditions.c.params.k).toBe('');
  });

  it('round-trips stored decimals and rejects bad strings', () => {
    expect(parseParam(atr, '0.3333333333333333')).toEqual({ value: 0.3333333333333333 });
    expect(parseParam(atr, '1e-7')).toEqual({ value: 1e-7 });
    const tag = { name: 't', label: 't', required: true, kind: 'string' as const };
    expect(parseParam(tag, 'a b').error).toBeDefined();
    expect(parseParam(tag, 'a'.repeat(33)).error).toBeDefined();
  });

  it('checks enums, booleans and strings', () => {
    expect(parseParam(kind, 'OB')).toEqual({ value: 'OB' });
    expect(parseParam(kind, 'XX').error).toBe('Choose one of the options.');
    expect(
      parseParam({ name: 'on', label: 'on', required: false, kind: 'boolean' }, 'true')
    ).toEqual({ value: true });
    expect(parseParam({ name: 't', label: 't', required: false, kind: 'string' }, 'abc')).toEqual({
      value: 'abc',
    });
    expect(parseParam({ name: 't', label: 't', required: false, kind: 'string' }, '')).toEqual({});
  });

  it.each([
    [{ min: 1 }, 'Enter a number of at least 1.'],
    [{ max: 9 }, 'Enter a number of at most 9.'],
    [{}, 'Enter a number.'],
  ])('words the range %j', (bounds, message) => {
    const field = { name: 'n', label: 'n', required: true, kind: 'number' as const, ...bounds };
    expect(parseParam(field, 'x').error).toBe(message);
  });
});

describe('parseStrategyForm', () => {
  it('builds the API body from the allow-listed fields in catalogue order', () => {
    const result = parse();
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.slug).toBe('my-setup');
    expect(result.body).toEqual({
      name: 'My setup',
      description: 'Fresh OB with the trend',
      zone_kinds: ['OB'],
      swing_length: 10,
      near_atr: 0.5,
      require: [{ key: 'fresh', params: {} }],
      score: [
        { key: 'aligned', params: {} },
        { key: 'max_zone_age', params: { bars: 50 } },
      ],
      min_score: 1,
      statuses: ['TOUCHING', 'NEAR'],
      mtf: false,
      require_htf_aligned: false,
    });
  });

  it('ignores unknown conditions, params and fields', () => {
    const result = parse({
      'cond.evil': 'require',
      'param.fresh.x': '1',
      builtin: 'true',
      'cond.in_ote': 'bogus',
    });
    expect(result.ok && result.body.require).toEqual([{ key: 'fresh', params: {} }]);
    expect(result.ok && 'builtin' in result.body).toBe(false);
  });

  it('ignores params of conditions that are off', () => {
    const result = parse({ 'cond.max_distance_atr': 'off', 'param.max_distance_atr.atr': 'oops' });
    expect(result.ok).toBe(true);
  });

  it('reports a bad param on its own field', () => {
    expect(errorsOf(parse({ 'param.max_zone_age.bars': '0' }))).toEqual({
      'param.max_zone_age.bars': 'Enter a whole number from 1 to 5000.',
    });
  });

  it('bounds min_score by the scored conditions', () => {
    expect(errorsOf(parse({ min_score: '3' })).min_score).toBe(
      'Enter a whole number from 0 to 2 (the scored conditions).'
    );
    expect(parse({ min_score: '' }).ok).toBe(true);
    expect(errorsOf(parse({ min_score: 'x' })).min_score).toBeDefined();
  });

  it('reports field errors and gives the values back', () => {
    const result = parse({
      name: '',
      slug: 'Bad Slug',
      swing_length: 'x',
      near_atr: '9',
      zone_kinds: [],
      statuses: ['NOPE'],
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(Object.keys(result.errors).sort()).toEqual([
      'name',
      'near_atr',
      'slug',
      'statuses',
      'swing_length',
      'zone_kinds',
    ]);
    expect(result.values.slug).toBe('Bad Slug');
    expect(result.values.conditions.fresh.mode).toBe('require');
  });

  it('needs mtf for require_htf_aligned', () => {
    expect(errorsOf(parse({ require_htf_aligned: 'on' })).require_htf_aligned).toBeDefined();
    expect(parse({ require_htf_aligned: 'on', mtf: 'on' }).ok).toBe(true);
  });

  it('refuses a built-in slug on create but ignores the slug on edit', () => {
    expect(errorsOf(parse({ slug: 'smc-default' })).slug).toBeDefined();
    const edit = parse({ slug: 'anything at all' }, 'edit');
    expect(edit.ok && 'slug' in edit.body).toBe(false);
  });

  it('reads boolean params and truncates long text', () => {
    const catalogue = [
      {
        key: 'flagged',
        label: 'Flagged',
        params: [{ name: 'on', label: 'On', required: false, kind: 'boolean' as const }],
      },
    ];
    const values = readFormValues(
      formOf({ 'cond.flagged': 'score', 'param.flagged.on': 'true', name: 'x'.repeat(3000) }),
      catalogue
    );
    expect(values.conditions.flagged).toEqual({ mode: 'score', params: { on: 'true' } });
    expect(values.name).toHaveLength(2000);
  });
});

describe('issue mapping', () => {
  it('puts a schema issue on a param on that param input', () => {
    const catalogue = [
      {
        key: 'big',
        label: 'Big',
        params: [{ name: 'n', label: 'N', required: true, kind: 'number' as const }],
      },
    ];
    const result = parseStrategyForm(
      formOf({ ...VALID_FORM, min_score: '0', 'cond.big': 'require', 'param.big.n': '9999999999' }),
      catalogue,
      'create'
    );
    expect(!result.ok && result.errors).toEqual({ 'param.big.n': 'Enter a smaller number.' });
  });

  it('round-trips a strategy with a long stored near_atr', () => {
    const values = valuesFromStrategy(makeStrategy({ near_atr: 1 / 3 }), CATALOGUE);
    const entries = {
      ...VALID_FORM,
      near_atr: values.near_atr,
    };
    expect(parseStrategyForm(formOf(entries), CATALOGUE, 'create').ok).toBe(true);
  });
});

describe('builder helpers', () => {
  it('counts the modes', () => {
    expect(countModes({ a: 'off', b: 'require', c: 'score', d: 'score' })).toEqual({
      off: 1,
      require: 1,
      score: 2,
    });
  });

  it('lowers a whole-number min_score above the scored count, and only that', () => {
    expect(lowerMinScore('3', 2)).toBe(2);
    expect(lowerMinScore('1', 0)).toBe(0);
    expect(lowerMinScore('1', 2)).toBeNull();
    expect(lowerMinScore('', 2)).toBeNull();
    // Never rewritten to the strictest value: non-whole text is flagged instead.
    expect(lowerMinScore('1.5', 0)).toBeNull();
    expect(lowerMinScore('1e1', 2)).toBeNull();
  });

  it('flags a min_score above the scored count', () => {
    expect(minScoreProblem('', 0)).toBeNull();
    expect(minScoreProblem('2', 2)).toBeNull();
    expect(minScoreProblem('3', 2)).toBe(
      'Enter a whole number from 0 to 2 (the scored conditions).'
    );
    expect(minScoreProblem('-1', 2)).not.toBeNull();
  });
});

describe('format', () => {
  it('describes conditions, scoring and tuning', () => {
    const strategy = makeStrategy({ mtf: true });
    expect(describeCondition(strategy.score[1], CATALOGUE)).toBe(
      'Zone at most N bars old (bars 50)'
    );
    expect(describeCondition({ key: 'gone', params: {} }, CATALOGUE)).toBe('gone');
    expect(describeScoring(strategy)).toBe('Scored, at least 1 of 2');
    expect(describeScoring({ score: [], min_score: 0 })).toBe('No scored conditions');
    expect(describeTuning(strategy)).toBe(
      'OB · touching or near · swing 10 · near 0.5 ATR · with HTF context'
    );
    expect(describeTuning(makeStrategy({ mtf: true, require_htf_aligned: true }))).toContain(
      'HTF must confirm'
    );
  });
});
