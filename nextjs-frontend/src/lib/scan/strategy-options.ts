import type { ConfigResponse } from '@/lib/api/scan';
import type { StrategyOut } from '@/lib/api/strategies';
import { DEFAULT_STRATEGY, isStrategySlug } from '@/lib/scan/params';

/**
 * The choices of the scan and schedule strategy pickers. They come from `GET /config`
 * `strategies` (built-ins only when the store is down), with `mtf` taken from `GET /strategies`
 * because the summary does not carry it; the full list is the fallback when /config failed.
 * Names are user text: render them as escaped text only.
 */

export type StrategyOption = {
  slug: string;
  name: string;
  builtin: boolean;
  swingLength: number;
  nearAtr: number;
  /** Whether the strategy turns multi-timeframe context on; false when unknown. */
  mtf: boolean;
};

const MAX_NAME = 100;
const MAX_OPTIONS = 200;

type Summary = {
  slug: string;
  name: string;
  builtin: boolean;
  swing_length: number;
  near_atr: number;
};

function isSummary(value: unknown): value is Summary {
  if (typeof value !== 'object' || value === null) return false;
  const item = value as Record<string, unknown>;
  return (
    isStrategySlug(item.slug) &&
    typeof item.name === 'string' &&
    item.name.length <= MAX_NAME &&
    typeof item.builtin === 'boolean' &&
    typeof item.swing_length === 'number' &&
    Number.isFinite(item.swing_length) &&
    typeof item.near_atr === 'number' &&
    Number.isFinite(item.near_atr)
  );
}

export function strategyOptions(
  config: Pick<ConfigResponse, 'strategies'> | null,
  strategies: ReadonlyArray<StrategyOut> | null
): StrategyOption[] {
  const mtfBySlug = new Map((strategies ?? []).map((item) => [item.slug, item.mtf]));
  // /config is only shape-checked for its choice lists, so its strategies are checked here.
  const fromConfig: unknown = config?.strategies;
  const summaries: unknown[] =
    Array.isArray(fromConfig) && fromConfig.length > 0 ? fromConfig : [...(strategies ?? [])];
  const seen = new Set<string>();
  return summaries
    .slice(0, MAX_OPTIONS)
    .filter(isSummary)
    .flatMap((item) => {
      if (seen.has(item.slug)) return [];
      seen.add(item.slug);
      return [
        {
          slug: item.slug,
          name: item.name,
          builtin: item.builtin,
          swingLength: item.swing_length,
          nearAtr: item.near_atr,
          mtf: mtfBySlug.get(item.slug) ?? false,
        },
      ];
    });
}

export function findStrategy(
  options: ReadonlyArray<StrategyOption>,
  slug: string
): StrategyOption | undefined {
  return options.find((option) => option.slug === slug);
}

/** The display name for a slug: the strategy's name when known, else the slug itself. */
export function strategyName(options: ReadonlyArray<StrategyOption>, slug: string): string {
  return findStrategy(options, slug)?.name ?? slug;
}

/**
 * Whether a slug should be flagged as missing. Only when the list is authoritative (the full
 * strategy list loaded) and the slug is not the always-present default.
 */
export function isMissingStrategy(known: ReadonlySet<string> | null, slug: string): boolean {
  return known !== null && slug !== DEFAULT_STRATEGY && !known.has(slug);
}
