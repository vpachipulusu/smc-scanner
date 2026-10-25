import type { StatusPillVariant } from '@/components/ui/status-pill';

/**
 * The survival verdict of a strategy's backtest as shown in the badges. The API says `pass`,
 * `fail` or `insufficient` for a finished run; no finished run is "Not run", and a finished run
 * whose stats could not be read has no verdict.
 */

export type ApiVerdict = 'pass' | 'fail' | 'insufficient' | null;

export type VerdictKey = 'survived' | 'failed' | 'insufficient' | 'not-run' | 'unknown';

/** Closed out-of-sample trades the API needs before it judges a strategy (`low_sample` below). */
export const MIN_CLOSED_TRADES = 30;

export const VERDICT_LABELS: Readonly<Record<VerdictKey, string>> = {
  survived: 'Survived',
  failed: 'Failed',
  insufficient: 'Insufficient',
  'not-run': 'Not run',
  unknown: 'No verdict',
};

export const VERDICT_VARIANTS: Readonly<Record<VerdictKey, StatusPillVariant>> = {
  survived: 'good',
  failed: 'crit',
  insufficient: 'warn',
  'not-run': 'neutral',
  unknown: 'neutral',
};

/** What each verdict means, for a title or a hint. */
export const VERDICT_DESCRIPTIONS: Readonly<Record<VerdictKey, string>> = {
  survived:
    'Out of sample, the 95% interval of the expectancy is above zero and the expectancy beats both the random and the flipped baselines.',
  failed:
    'Out of sample, the expectancy interval reaches zero or the expectancy does not beat both baselines.',
  insufficient: `Fewer than ${MIN_CLOSED_TRADES} closed out-of-sample trades (or baseline trades), too few to judge. Use more bars or symbols.`,
  'not-run': 'This strategy has no finished backtest yet.',
  unknown: 'The latest run finished, but its statistics could not be read.',
};

/** The verdict of a finished run. */
export function verdictKey(verdict: ApiVerdict | undefined): VerdictKey {
  switch (verdict) {
    case 'pass':
      return 'survived';
    case 'fail':
      return 'failed';
    case 'insufficient':
      return 'insufficient';
    default:
      return 'unknown';
  }
}

/** Verdicts by slug; a slug left out (its read failed) shows no badge. */
export type StrategyVerdicts = Readonly<Record<string, VerdictKey>>;

/** A slug's verdict, own keys only (a slug such as "constructor" must not hit the prototype). */
export function verdictFor(verdicts: StrategyVerdicts, slug: string): VerdictKey | undefined {
  return Object.hasOwn(verdicts, slug) ? verdicts[slug] : undefined;
}

/** The badge of a strategy: its latest finished run's verdict, or "Not run" without one. */
export function badgeVerdict(latest: { verdict: ApiVerdict } | null): VerdictKey {
  return latest === null ? 'not-run' : verdictKey(latest.verdict);
}
