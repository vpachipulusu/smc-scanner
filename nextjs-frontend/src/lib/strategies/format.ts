import type { StrategyOut } from '@/lib/api/strategies-write';
import { conditionLabel, type ConditionInfo } from './catalogue';

/** Display text for a strategy's conditions on the list. All of it is rendered as escaped text. */

type Ref = StrategyOut['require'][number];

/** "Zone at most N bars old (bars 50)": the condition's label plus any params. */
export function describeCondition(ref: Ref, catalogue: readonly ConditionInfo[]): string {
  const label = conditionLabel(catalogue, ref.key);
  const params = Object.entries(ref.params).map(([name, value]) => `${name} ${String(value)}`);
  return params.length === 0 ? label : `${label} (${params.join(', ')})`;
}

export function describeScoring(strategy: Pick<StrategyOut, 'score' | 'min_score'>): string {
  const total = strategy.score.length;
  if (total === 0) return 'No scored conditions';
  return `Scored, at least ${strategy.min_score} of ${total}`;
}

export function describeTuning(strategy: StrategyOut): string {
  const parts = [
    strategy.zone_kinds.join(' + '),
    strategy.statuses.map((status) => status.toLowerCase()).join(' or '),
    `swing ${strategy.swing_length}`,
    `near ${strategy.near_atr} ATR`,
  ];
  if (strategy.mtf)
    parts.push(strategy.require_htf_aligned ? 'HTF must confirm' : 'with HTF context');
  return parts.join(' · ');
}
