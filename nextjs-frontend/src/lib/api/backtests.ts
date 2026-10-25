import 'server-only';

import { cache } from 'react';

import { badgeVerdict, type VerdictKey } from '@/lib/backtests/verdict';
import { isStrategySlug } from '@/lib/scan/params';
import { callBackend, type ApiResult } from './server';
import {
  BACKTESTS_REQUEST_FAILED_MESSAGE,
  backtestErrorMessage,
  retryDelayMs,
} from './backtests-messages';
import {
  createBacktest,
  getBacktest,
  getStrategyBacktest,
  listBacktests,
  type BacktestCreate,
  type BacktestListItem,
  type BacktestOut,
  type BacktestResultsOut,
  type BacktestStatsOut,
  type BacktestSummaryOut,
  type ExitRulesIn,
  type ExitRulesOut,
} from './generated';

/**
 * Server-only calls behind the backtest pages and the verdict badges: list, read, the latest
 * finished run of a strategy (a 404 there is "not run", not an error) and start. Callers import
 * these instead of the generated SDK. Every failure becomes one of the fixed messages in
 * `backtests-messages.ts`; the API's own error text is only matched, never passed on. Response
 * bodies are shape-checked before use.
 */

export type {
  BacktestCreate,
  BacktestListItem,
  BacktestOut,
  BacktestResultsOut,
  BacktestStatsOut,
  BacktestSummaryOut,
  ExitRulesIn,
  ExitRulesOut,
};

export type BacktestFailure = {
  success: false;
  error: string;
  status?: number;
  /** Seconds from the `Retry-After` header of a 429. */
  retryAfter?: number;
};

export type BacktestResult<T> = { success: true; data: T } | BacktestFailure;

/**
 * A started run: its id (from the `Location` header, else the body) and the pending row, which is
 * null when only the header could be read (the run is queued all the same).
 */
export type StartedBacktest = { id: number; backtest: BacktestOut | null };

/** The API's `limit` range on GET /backtests. */
export const MAX_LIST_LIMIT = 200;
/** Badges are one request each against a 60 per minute bucket; past this many, the rest show none. */
export const MAX_BADGE_REQUESTS = 30;
/**
 * How long a read verdict is reused across requests. /scan re-renders on its auto-refresh and
 * every page view would otherwise re-read each badge from the shared 60 per minute bucket.
 */
export const VERDICT_TTL_MS = 60_000;
const MAX_CACHED_VERDICTS = 500;
/**
 * After a 401, 429 or 503 on a badge read, badges are skipped this long, or for the Retry-After
 * (at most `MAX_BACKOFF_MS`).
 */
export const VERDICT_BACKOFF_MS = 30_000;
const BACKOFF_STATUSES: ReadonlySet<number | undefined> = new Set([undefined, 401, 429, 503]);

const STATUSES: readonly unknown[] = ['pending', 'running', 'done', 'failed'];
const VERDICTS: readonly unknown[] = ['pass', 'fail', 'insufficient', null];
const RULE_KEYS = ['rr', 'stop_buffer_atr', 'time_stop_bars', 'spread', 'min_risk_atr'] as const;
const STAT_COUNTS = ['n', 'n_open', 'n_void'] as const;
const STAT_RATIOS = [
  'hit_rate',
  'average_r',
  'expectancy_r',
  'median_r',
  'best_r',
  'worst_r',
  'total_r',
  'profit_factor',
  'max_drawdown_r',
  'avg_bars_held',
  'ci_low',
  'ci_high',
] as const;
const MAX_TEXT = 200;
const LOCATION_PATTERN = /\/backtests\/(\d{1,15})$/;

function isRecord(body: unknown): body is Record<string, unknown> {
  return typeof body === 'object' && body !== null && !Array.isArray(body);
}

const isNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const isNullableNumber = (value: unknown): boolean => value === null || isNumber(value);
const isId = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const isText = (value: unknown): value is string =>
  typeof value === 'string' && value.length <= MAX_TEXT;
const isNullableText = (value: unknown): boolean => value === null || isText(value);
const isOptional = (value: unknown, check: (item: unknown) => boolean): boolean =>
  value === undefined || value === null || check(value);

function isStats(body: unknown): body is BacktestStatsOut {
  return (
    isRecord(body) &&
    STAT_COUNTS.every((key) => isNumber(body[key])) &&
    typeof body.low_sample === 'boolean' &&
    STAT_RATIOS.every((key) => isNullableNumber(body[key]))
  );
}

function isResults(body: unknown): body is BacktestResultsOut {
  return (
    isRecord(body) &&
    isOptional(body.pooled, isStats) &&
    isOptional(body.in_sample, isStats) &&
    isOptional(body.out_of_sample, isStats) &&
    isOptional(body.baselines, (value) => isRecord(value) && Object.values(value).every(isStats))
  );
}

const isRules = (body: unknown): body is ExitRulesOut =>
  isRecord(body) && RULE_KEYS.every((key) => isNumber(body[key]));

/** The fields every backtest row shares (list item and full row). */
function isRunRow(body: Record<string, unknown>): boolean {
  return (
    isId(body.id) &&
    isText(body.created_at) &&
    isStrategySlug(body.strategy) &&
    isText(body.source) &&
    isText(body.tf) &&
    isNumber(body.bars) &&
    STATUSES.includes(body.status) &&
    VERDICTS.includes(body.verdict) &&
    isNullableNumber(body.duration_seconds) &&
    isNullableText(body.error)
  );
}

function isBacktest(body: unknown): body is BacktestOut {
  return (
    isRecord(body) &&
    isRunRow(body) &&
    Array.isArray(body.symbols) &&
    body.symbols.every(isText) &&
    (body.rules === null || isRules(body.rules)) &&
    isText(body.split) &&
    isNullableNumber(body.train_fraction) &&
    isNumber(body.seed) &&
    isNumber(body.stride) &&
    (body.results === null || isResults(body.results))
  );
}

/** The badge figures shared by a list item and the strategy summary. */
function hasBadgeFigures(body: Record<string, unknown>): boolean {
  return (
    isNullableNumber(body.n) &&
    isNullableNumber(body.expectancy_r) &&
    isNullableNumber(body.ci_low) &&
    isNullableNumber(body.ci_high) &&
    (body.low_sample === null || typeof body.low_sample === 'boolean')
  );
}

const isListItem = (body: unknown): body is BacktestListItem =>
  isRecord(body) && isRunRow(body) && hasBadgeFigures(body);

const isSummary = (body: unknown): body is BacktestSummaryOut =>
  isRecord(body) &&
  isId(body.id) &&
  isStrategySlug(body.strategy) &&
  isText(body.created_at) &&
  VERDICTS.includes(body.verdict) &&
  hasBadgeFigures(body);

/**
 * Parses `Retry-After` as whole seconds of at least 1; an HTTP date, a fraction or 0 is ignored.
 * Waits built from it are capped by `retryDelayMs`.
 */
export function parseRetryAfter(header: string | null | undefined): number | undefined {
  if (!header || !/^\d{1,6}$/.test(header)) return undefined;
  const seconds = Number(header);
  return seconds >= 1 ? seconds : undefined;
}

/** The id in a `Location: /backtests/{id}` header, or null. */
export function locationId(header: string | null | undefined): number | null {
  const match = header ? LOCATION_PATTERN.exec(header) : null;
  if (!match) return null;
  const id = Number(match[1]);
  return isId(id) ? id : null;
}

function badBody(): BacktestFailure {
  return { success: false, error: BACKTESTS_REQUEST_FAILED_MESSAGE, status: 502 };
}

function failure(result: { status?: number; error: string }, retryAfter?: number): BacktestFailure {
  return {
    success: false,
    error: backtestErrorMessage({ status: result.status, retryAfter, reason: result.error }),
    status: result.status,
    ...(retryAfter === undefined ? {} : { retryAfter }),
  };
}

type SdkCall<T> = Parameters<typeof callBackend<T>>[0];

type Called<T> = { result: ApiResult<T>; retryAfter?: number; location?: string | null };

/** `callBackend` plus the `Retry-After` and `Location` headers. */
async function call<T>(sdkCall: SdkCall<T>): Promise<Called<T>> {
  let retryAfter: number | undefined;
  let location: string | null | undefined;
  const result = await callBackend<T>(async (client) => {
    const response = await sdkCall(client);
    retryAfter = parseRetryAfter(response.response?.headers.get('Retry-After'));
    location = response.response?.headers.get('Location');
    return response;
  });
  return { result, retryAfter, location };
}

/** Newest first, without results. `strategy` narrows the list to one strategy. */
export async function fetchBacktests(
  strategy?: string,
  limit = 50
): Promise<BacktestResult<BacktestListItem[]>> {
  if (strategy !== undefined && !isStrategySlug(strategy)) {
    return { success: true, data: [] };
  }
  const wanted = Number.isFinite(limit) ? Math.trunc(limit) : 50;
  const safeLimit = Math.min(Math.max(wanted, 1), MAX_LIST_LIMIT);
  const { result, retryAfter } = await call((client) =>
    listBacktests({ client, query: { limit: safeLimit, ...(strategy ? { strategy } : {}) } })
  );
  if (!result.success) return failure(result, retryAfter);
  const items: unknown = isRecord(result.data) ? result.data.items : null;
  // A partly invalid list must not read as fewer runs (a hidden in-flight row would re-enable Run).
  if (!Array.isArray(items) || items.length > MAX_LIST_LIMIT || !items.every(isListItem)) {
    return badBody();
  }
  return { success: true, data: items };
}

export async function fetchBacktest(id: number): Promise<BacktestResult<BacktestOut>> {
  if (!isId(id)) return failure({ status: 404, error: '' });
  const { result, retryAfter } = await call((client) =>
    getBacktest({ client, path: { backtest_id: id } })
  );
  if (!result.success) return failure(result, retryAfter);
  if (!isBacktest(result.data)) return badBody();
  // A run that just ended may change its strategy's badge: read it afresh next time.
  if (result.data.status === 'done') invalidateVerdict(result.data.strategy);
  return { success: true, data: result.data };
}

/**
 * The badge of a strategy's latest finished run; `null` when it has none (the API's 404). Cached
 * per request, so a page and its pickers asking for the same slug cost one call.
 */
export const fetchLatestBacktest = cache(
  async (slug: string): Promise<BacktestResult<BacktestSummaryOut | null>> => {
    if (!isStrategySlug(slug)) return { success: true, data: null };
    const { result, retryAfter } = await call((client) =>
      getStrategyBacktest({ client, path: { slug } })
    );
    if (!result.success) {
      return result.status === 404 ? { success: true, data: null } : failure(result, retryAfter);
    }
    return isSummary(result.data) ? { success: true, data: result.data } : badBody();
  }
);

/** Verdicts read in the last `VERDICT_TTL_MS`, by slug (this server process only). */
const verdictCache = new Map<string, { verdict: VerdictKey; expires: number }>();

/**
 * A slug's badge must not be re-cached by a read that began before one of its runs ended: each
 * invalidation takes the next `generation`, and a read only remembers its verdict when nothing
 * newer than its start touched the slug (or wiped the cache).
 */
let generation = 0;
let wipedAt = 0;
const invalidatedAt = new Map<string, number>();

/** Until when badge reads are skipped after the API refused or failed one. */
let verdictBackoffUntil = 0;

function wipeVerdicts(): void {
  verdictCache.clear();
  invalidatedAt.clear();
  generation += 1;
  wipedAt = generation;
}

/** Forgets every cached verdict and any backoff (tests, or after a known change). */
export function clearVerdictCache(): void {
  wipeVerdicts();
  verdictBackoffUntil = 0;
}

function invalidateVerdict(slug: string): void {
  if (invalidatedAt.size >= MAX_CACHED_VERDICTS) wipeVerdicts();
  verdictCache.delete(slug);
  generation += 1;
  invalidatedAt.set(slug, generation);
}

function cachedVerdict(slug: string, now: number): VerdictKey | undefined {
  const hit = verdictCache.get(slug);
  if (hit && hit.expires > now) return hit.verdict;
  if (hit) verdictCache.delete(slug);
  return undefined;
}

function rememberVerdict(slug: string, verdict: VerdictKey, now: number, startedAt: number): void {
  if (wipedAt > startedAt || (invalidatedAt.get(slug) ?? 0) > startedAt) return;
  if (verdictCache.size >= MAX_CACHED_VERDICTS) verdictCache.clear();
  verdictCache.set(slug, { verdict, expires: now + VERDICT_TTL_MS });
}

/**
 * A slug's badge, read and remembered when the read worked. "Not run" (the API's 404, which is
 * also its answer for an unknown slug) is never remembered, so a bad slug cannot fill the cache.
 */
async function readVerdict(slug: string, now: number): Promise<VerdictKey | undefined> {
  const startedAt = generation;
  const result = await fetchLatestBacktest(slug);
  if (!result.success) {
    // Down, refusing the key or over the rate limit: stop spending the shared bucket for a while.
    if (BACKOFF_STATUSES.has(result.status)) {
      const wait = retryDelayMs(result.retryAfter, VERDICT_BACKOFF_MS);
      verdictBackoffUntil = Math.max(verdictBackoffUntil, now + wait);
    }
    return undefined;
  }
  const verdict = badgeVerdict(result.data);
  if (result.data !== null) rememberVerdict(slug, verdict, now, startedAt);
  return verdict;
}

/**
 * The verdict of each listed strategy: fresh cached ones first, then up to `MAX_BADGE_REQUESTS`
 * of the rest read in parallel. A slug whose read failed (or was skipped) is left out, so it
 * shows no badge rather than a wrong one.
 */
export async function fetchBacktestVerdicts(
  slugs: readonly string[]
): Promise<Record<string, VerdictKey>> {
  const now = Date.now();
  const verdicts: Record<string, VerdictKey> = {};
  const misses: string[] = [];
  for (const slug of new Set(slugs)) {
    const cached = cachedVerdict(slug, now);
    if (cached === undefined) misses.push(slug);
    else verdicts[slug] = cached;
  }
  if (now < verdictBackoffUntil) return verdicts;
  const toRead = misses.slice(0, MAX_BADGE_REQUESTS);
  const settled = await Promise.allSettled(toRead.map((slug) => readVerdict(slug, now)));
  settled.forEach((outcome, index) => {
    if (outcome.status === 'fulfilled') {
      if (outcome.value !== undefined) verdicts[toRead[index]] = outcome.value;
    } else {
      console.error('Backtest badge read failed', { slug: toRead[index], reason: outcome.reason });
    }
  });
  return verdicts;
}

/** Starts a run (202): the pending row, with its id from `Location` (the body's id otherwise). */
export async function startBacktest(
  body: BacktestCreate
): Promise<BacktestResult<StartedBacktest>> {
  const { result, retryAfter, location } = await call((client) => createBacktest({ client, body }));
  if (!result.success) return failure(result, retryAfter);
  const fromHeader = locationId(location);
  if (!isBacktest(result.data)) {
    // The run is queued (202); without a readable row its Location still names it.
    return fromHeader === null
      ? badBody()
      : { success: true, data: { id: fromHeader, backtest: null } };
  }
  return { success: true, data: { id: fromHeader ?? result.data.id, backtest: result.data } };
}
