import type { ConditionInfo, StrategyOut } from '@/lib/api/strategies-write';
import { toConditionInfo } from '@/lib/strategies/catalogue';

/** `/config` `conditions` as the API sends them today (a subset, with every params kind). */
export const RAW_CONDITIONS = [
  {
    key: 'aligned',
    label: 'Zone direction matches the trend',
    params_schema: { properties: {}, type: 'object' },
  },
  {
    key: 'in_ote',
    label: 'Zone overlaps the OTE band',
    params_schema: { properties: {}, type: 'object' },
  },
  { key: 'fresh', label: 'First touch only', params_schema: { properties: {}, type: 'object' } },
  {
    key: 'max_zone_age',
    label: 'Zone at most N bars old',
    params_schema: {
      properties: { bars: { maximum: 5000, minimum: 1, title: 'Bars', type: 'integer' } },
      required: ['bars'],
      type: 'object',
    },
  },
  {
    key: 'max_distance_atr',
    label: 'Price within N ATR of the zone',
    params_schema: {
      properties: { atr: { maximum: 5.0, minimum: 0, title: 'Atr', type: 'number' } },
      required: ['atr'],
      type: 'object',
    },
  },
  {
    key: 'zone_kind',
    label: 'Zone is of the given kind',
    params_schema: {
      properties: { kind: { enum: ['FVG', 'OB'], title: 'Kind', type: 'string' } },
      required: ['kind'],
      type: 'object',
    },
  },
] as const;

export const CATALOGUE: ConditionInfo[] = RAW_CONDITIONS.map((raw) => {
  const info = toConditionInfo(raw);
  if (info === null) throw new Error(`bad fixture ${raw.key}`);
  return info;
});

export function makeStrategy(overrides: Partial<StrategyOut> = {}): StrategyOut {
  return {
    slug: 'my-setup',
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
    builtin: false,
    ...overrides,
  };
}

export const BUILTIN = makeStrategy({
  slug: 'smc-default',
  name: 'SMC default',
  description: 'Scored 0-4.',
  zone_kinds: ['FVG', 'OB'],
  require: [],
  score: [
    { key: 'aligned', params: {} },
    { key: 'in_ote', params: {} },
  ],
  min_score: 0,
  builtin: true,
});

/** A FormData from plain entries; arrays become repeated keys. */
export function formOf(entries: Record<string, string | readonly string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    for (const item of typeof value === 'string' ? [value] : value) data.append(key, item);
  }
  return data;
}

/** A valid create form: one required, two scored (one with a param). */
export const VALID_FORM: Readonly<Record<string, string | readonly string[]>> = {
  mode: 'create',
  slug: 'my-setup',
  name: 'My setup',
  description: 'Fresh OB with the trend',
  zone_kinds: ['OB'],
  swing_length: '10',
  near_atr: '0.5',
  statuses: ['TOUCHING', 'NEAR'],
  min_score: '1',
  'cond.fresh': 'require',
  'cond.aligned': 'score',
  'cond.max_zone_age': 'score',
  'param.max_zone_age.bars': '50',
};
