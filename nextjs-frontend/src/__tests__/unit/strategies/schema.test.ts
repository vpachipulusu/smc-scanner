/** The zod schemas mirror the API's StrategyCreate / StrategyUpdate rules and cross-field checks. */
import { describe, expect, it } from 'vitest';

import {
  BUILTIN_SLUG_MESSAGE,
  isBuiltinSlug,
  slugSchema,
  strategyCreateSchema,
  strategyUpdateSchema,
} from '@/lib/strategies/schema';

const BODY = {
  name: 'My setup',
  description: '',
  zone_kinds: ['FVG', 'OB'],
  swing_length: 10,
  near_atr: 0.5,
  require: [{ key: 'fresh', params: {} }],
  score: [
    { key: 'aligned', params: {} },
    { key: 'max_zone_age', params: { bars: 50 } },
  ],
  min_score: 2,
  statuses: ['TOUCHING'],
  mtf: false,
  require_htf_aligned: false,
};

const messages = (result: { success: boolean; error?: { issues: { message: string }[] } }) =>
  result.success ? [] : (result.error?.issues.map((issue) => issue.message) ?? []);

describe('slugSchema', () => {
  it.each(['a', 'my-setup', '0x', 'a'.repeat(32)])('accepts %s', (slug) => {
    expect(slugSchema.safeParse(slug).success).toBe(true);
  });

  it.each(['', '-a', 'A', 'a_b', 'a b', 'a'.repeat(33), 'a\n'])('rejects %j', (slug) => {
    expect(slugSchema.safeParse(slug).success).toBe(false);
  });
});

describe('strategyUpdateSchema', () => {
  it('accepts a valid body and trims the text', () => {
    const result = strategyUpdateSchema.safeParse({ ...BODY, name: '  My setup  ' });
    expect(result.success && result.data.name).toBe('My setup');
  });

  it.each([
    ['empty name', { name: '' }],
    ['name without letters or digits', { name: '---' }],
    ['name outside the alphabet', { name: 'My <b>setup</b>' }],
    ['name too long', { name: 'a'.repeat(65) }],
    ['description outside the alphabet', { description: 'a; drop' }],
    ['description too long', { description: 'a'.repeat(281) }],
    ['no zone kinds', { zone_kinds: [] }],
    ['duplicate zone kinds', { zone_kinds: ['OB', 'OB'] }],
    ['unknown zone kind', { zone_kinds: ['XX'] }],
    ['no statuses', { statuses: [] }],
    ['swing length 0', { swing_length: 0 }],
    ['swing length 101', { swing_length: 101 }],
    ['fractional swing length', { swing_length: 2.5 }],
    ['NaN swing length', { swing_length: Number.NaN }],
    ['negative near', { near_atr: -0.1 }],
    ['near above 5', { near_atr: 5.01 }],
    ['negative min score', { min_score: -1 }],
    ['an extra field', { builtin: true }],
    ['a slug on update', { slug: 'x' }],
  ])('rejects %s', (_label, patch) => {
    expect(strategyUpdateSchema.safeParse({ ...BODY, ...patch }).success).toBe(false);
  });

  it('allows the full alphabet in the name and description', () => {
    const text = "Fresh OB, 50% (OTE) / trend & co. - it's ok";
    const body = { ...BODY, name: text, description: text };
    expect(strategyUpdateSchema.safeParse(body).success).toBe(true);
  });

  it('rejects more than 12 conditions in a list', () => {
    const many = Array.from({ length: 13 }, (_, index) => ({ key: `c${index}`, params: {} }));
    const result = strategyUpdateSchema.safeParse({ ...BODY, require: many });
    expect(messages(result)).toContain('Use at most 12 conditions.');
  });

  it('rejects a condition used twice across the lists', () => {
    const body = { ...BODY, require: [{ key: 'aligned', params: {} }] };
    expect(messages(strategyUpdateSchema.safeParse(body))).toContain(
      'A condition can be used only once.'
    );
  });

  it('bounds min_score by the number of scored conditions', () => {
    expect(strategyUpdateSchema.safeParse({ ...BODY, min_score: 2 }).success).toBe(true);
    const result = strategyUpdateSchema.safeParse({ ...BODY, min_score: 3 });
    expect(messages(result)).toContain('Enter a whole number from 0 to 2 (the scored conditions).');
  });

  it('needs mtf for require_htf_aligned', () => {
    const without = strategyUpdateSchema.safeParse({ ...BODY, require_htf_aligned: true });
    expect(messages(without)).toContain('Include higher timeframe context first.');
    const withMtf = { ...BODY, mtf: true, require_htf_aligned: true };
    expect(strategyUpdateSchema.safeParse(withMtf).success).toBe(true);
  });

  const nineParams = Object.fromEntries(Array.from({ length: 9 }, (_, i) => [`p${i}`, i]));

  it.each([
    ['a bad condition key', { key: 'Bad', params: {} }],
    ['a bad param name', { key: 'x', params: { 'Bad-Name': 1 } }],
    ['a long param string', { key: 'x', params: { kind: 'a'.repeat(33) } }],
    ['a param string outside the alphabet', { key: 'x', params: { kind: 'a b' } }],
    ['an infinite param', { key: 'x', params: { atr: Number.POSITIVE_INFINITY } }],
    ['a huge param', { key: 'x', params: { atr: 1e10 } }],
    ['an extra ref field', { key: 'x', params: {}, extra: 1 }],
    ['too many params', { key: 'x', params: nineParams }],
  ])('rejects %s', (_label, ref) => {
    expect(strategyUpdateSchema.safeParse({ ...BODY, require: [ref] }).success).toBe(false);
  });

  it('accepts boolean, number and short string params', () => {
    const ref = { key: 'x', params: { on: true, atr: 1.5, kind: 'OB' } };
    expect(strategyUpdateSchema.safeParse({ ...BODY, require: [ref] }).success).toBe(true);
  });
});

describe('strategyCreateSchema', () => {
  it('needs a valid slug', () => {
    expect(strategyCreateSchema.safeParse({ ...BODY, slug: 'my-setup' }).success).toBe(true);
    expect(strategyCreateSchema.safeParse({ ...BODY, slug: 'My Setup' }).success).toBe(false);
    expect(strategyCreateSchema.safeParse(BODY).success).toBe(false);
  });

  it('refuses a built-in slug', () => {
    const result = strategyCreateSchema.safeParse({ ...BODY, slug: 'smc-default' });
    expect(messages(result)).toContain(BUILTIN_SLUG_MESSAGE);
  });

  it('still applies the cross-field rules', () => {
    expect(strategyCreateSchema.safeParse({ ...BODY, slug: 'x', min_score: 9 }).success).toBe(
      false
    );
  });
});

describe('isBuiltinSlug', () => {
  it('knows the five built-ins', () => {
    const builtins = [
      'smc-default',
      'fresh-ob-trend',
      'fvg-ote-reversal',
      'htf-aligned-touch',
      'valid-ob',
    ];
    expect(builtins.every(isBuiltinSlug)).toBe(true);
    expect(isBuiltinSlug('my-setup')).toBe(false);
  });
});
