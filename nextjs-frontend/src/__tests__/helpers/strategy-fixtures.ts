import type { StrategyOut } from '@/lib/api/strategies';
import type { StrategyOption } from '@/lib/scan/strategy-options';

/** The built-in default strategy, shaped like GET /strategies items. */
export function makeStrategy(overrides: Partial<StrategyOut> = {}): StrategyOut {
  return {
    slug: 'smc-default',
    name: 'SMC default',
    description: '',
    zone_kinds: ['FVG', 'OB'],
    swing_length: 10,
    near_atr: 0.5,
    require: [],
    score: [{ key: 'aligned', params: {} }],
    min_score: 0,
    statuses: ['TOUCHING', 'NEAR'],
    mtf: false,
    require_htf_aligned: false,
    builtin: true,
    ...overrides,
  };
}

export const OPTIONS: StrategyOption[] = [
  {
    slug: 'smc-default',
    name: 'SMC default',
    builtin: true,
    swingLength: 10,
    nearAtr: 0.5,
    mtf: false,
  },
  {
    slug: 'htf-aligned-touch',
    name: 'HTF aligned touch',
    builtin: true,
    swingLength: 8,
    nearAtr: 0.3,
    mtf: true,
  },
  { slug: 'my-setup', name: 'My setup', builtin: false, swingLength: 5, nearAtr: 1, mtf: false },
];
