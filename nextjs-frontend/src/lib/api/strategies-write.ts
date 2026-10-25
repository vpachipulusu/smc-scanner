import 'server-only';

import { toConditionInfo, type ConditionInfo } from '@/lib/strategies/catalogue';
import { SLUG_PATTERN, STRATEGY_LIMITS } from '@/lib/strategies/schema';
import { callBackend, type ApiResult } from './server';
import {
  CONDITIONS_UNAVAILABLE_MESSAGE,
  STRATEGIES_REQUEST_FAILED_MESSAGE,
  STRATEGY_NOT_FOUND_MESSAGE,
  strategyErrorMessage,
} from './strategies-write-messages';
import {
  config,
  createStrategy,
  deleteStrategy,
  getStrategy,
  listStrategies,
  updateStrategy,
  type StrategyCreate,
  type StrategyOut,
  type StrategyUpdate,
} from './generated';

/**
 * Server-only calls behind the /strategies page: list, read, create, update and delete, plus the
 * condition catalogue from `/config`. Callers import these instead of the generated SDK. Every
 * failure becomes one of the fixed messages in `strategies-write-messages.ts`; the API's own error
 * text is only matched, never passed on. Response bodies are shape-checked before use.
 */

export type { ConditionInfo, StrategyCreate, StrategyOut, StrategyUpdate };

export type StrategyResult<T> =
  { success: true; data: T } | { success: false; error: string; status?: number };

type Failure = { success: false; error: string; status?: number };

const ZONE_KINDS: readonly unknown[] = ['FVG', 'OB'];
const STATUSES: readonly unknown[] = ['TOUCHING', 'NEAR'];

function isRecord(body: unknown): body is Record<string, unknown> {
  return typeof body === 'object' && body !== null && !Array.isArray(body);
}

const isNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const isBoundedString = (value: unknown, max: number): boolean =>
  typeof value === 'string' && value.length <= max;

const isParamValue = (value: unknown): boolean =>
  typeof value === 'string' || typeof value === 'boolean' || isNumber(value);

function isConditionRef(body: unknown): boolean {
  return (
    isRecord(body) &&
    typeof body.key === 'string' &&
    isRecord(body.params) &&
    Object.values(body.params).every(isParamValue)
  );
}

const listOf = (value: unknown, check: (item: unknown) => boolean): boolean =>
  Array.isArray(value) && value.every(check);

function isStrategy(body: unknown): body is StrategyOut {
  return (
    isRecord(body) &&
    typeof body.slug === 'string' &&
    SLUG_PATTERN.test(body.slug) &&
    isBoundedString(body.name, STRATEGY_LIMITS.nameMax) &&
    isBoundedString(body.description, STRATEGY_LIMITS.descriptionMax) &&
    listOf(body.zone_kinds, (kind) => ZONE_KINDS.includes(kind)) &&
    isNumber(body.swing_length) &&
    isNumber(body.near_atr) &&
    listOf(body.require, isConditionRef) &&
    listOf(body.score, isConditionRef) &&
    isNumber(body.min_score) &&
    listOf(body.statuses, (status) => STATUSES.includes(status)) &&
    typeof body.mtf === 'boolean' &&
    typeof body.require_htf_aligned === 'boolean' &&
    typeof body.builtin === 'boolean'
  );
}

function badBody(message = STRATEGIES_REQUEST_FAILED_MESSAGE): Failure {
  return { success: false, error: message, status: 502 };
}

function failure(result: { status?: number; error: string }, retryAfter?: number): Failure {
  return {
    success: false,
    error: strategyErrorMessage({ status: result.status, retryAfter, reason: result.error }),
    status: result.status,
  };
}

/** A path slug that cannot exist is "not found" without asking the API. */
function badSlug(): Failure {
  return { success: false, error: STRATEGY_NOT_FOUND_MESSAGE, status: 404 };
}

/** Parses `Retry-After` (whole seconds); anything else is ignored. */
function parseRetryAfter(header: string | null | undefined): number | undefined {
  if (!header || !/^\d{1,6}$/.test(header)) return undefined;
  return Number(header);
}

type SdkCall<T> = Parameters<typeof callBackend<T>>[0];

/** `callBackend` plus the `Retry-After` header of a 429. */
async function call<T>(
  sdkCall: SdkCall<T>
): Promise<{ result: ApiResult<T>; retryAfter?: number }> {
  let retryAfter: number | undefined;
  const result = await callBackend<T>(async (client) => {
    const response = await sdkCall(client);
    retryAfter = parseRetryAfter(response.response?.headers.get('Retry-After'));
    return response;
  });
  return { result, retryAfter };
}

/** Built-ins first, then stored strategies by slug (the API's order). */
export async function fetchStrategies(): Promise<StrategyResult<StrategyOut[]>> {
  const { result, retryAfter } = await call((client) => listStrategies({ client }));
  if (!result.success) return failure(result, retryAfter);
  const items: unknown = isRecord(result.data) ? result.data.items : null;
  if (!Array.isArray(items)) return badBody();
  const strategies = items.filter(isStrategy);
  // A partly invalid list must not read as a shorter list; treat contract drift as a failure.
  if (strategies.length !== items.length) return badBody();
  return { success: true, data: strategies };
}

export async function fetchStrategy(slug: string): Promise<StrategyResult<StrategyOut>> {
  if (!SLUG_PATTERN.test(slug)) return badSlug();
  const { result, retryAfter } = await call((client) => getStrategy({ client, path: { slug } }));
  if (!result.success) return failure(result, retryAfter);
  return isStrategy(result.data) ? { success: true, data: result.data } : badBody();
}

export async function addStrategy(body: StrategyCreate): Promise<StrategyResult<StrategyOut>> {
  const { result, retryAfter } = await call((client) => createStrategy({ client, body }));
  if (!result.success) return failure(result, retryAfter);
  return isStrategy(result.data) ? { success: true, data: result.data } : badBody();
}

export async function editStrategy(
  slug: string,
  body: StrategyUpdate
): Promise<StrategyResult<StrategyOut>> {
  if (!SLUG_PATTERN.test(slug)) return badSlug();
  const { result, retryAfter } = await call((client) =>
    updateStrategy({ client, path: { slug }, body })
  );
  if (!result.success) return failure(result, retryAfter);
  return isStrategy(result.data) ? { success: true, data: result.data } : badBody();
}

export async function removeStrategy(slug: string): Promise<StrategyResult<null>> {
  if (!SLUG_PATTERN.test(slug)) return badSlug();
  const { result, retryAfter } = await call((client) => deleteStrategy({ client, path: { slug } }));
  if (!result.success) return failure(result, retryAfter);
  return { success: true, data: null };
}

/** The condition catalogue from `/config`; any entry the builder cannot render fails the lot. */
export async function fetchConditionCatalogue(): Promise<StrategyResult<ConditionInfo[]>> {
  const { result } = await call((client) => config({ client }));
  if (!result.success)
    return { success: false, error: CONDITIONS_UNAVAILABLE_MESSAGE, status: result.status };
  const raw: unknown = isRecord(result.data) ? result.data.conditions : null;
  if (!Array.isArray(raw)) return badBody(CONDITIONS_UNAVAILABLE_MESSAGE);
  const catalogue = raw.map(toConditionInfo);
  const valid = catalogue.filter((info): info is ConditionInfo => info !== null);
  const keys = new Set(valid.map((info) => info.key));
  if (valid.length !== raw.length || keys.size !== valid.length) {
    return badBody(CONDITIONS_UNAVAILABLE_MESSAGE);
  }
  return { success: true, data: valid };
}
