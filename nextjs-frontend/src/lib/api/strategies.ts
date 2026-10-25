import 'server-only';

import { callBackend } from './server';
import { STRATEGIES_REQUEST_FAILED_MESSAGE, strategiesErrorMessage } from './strategies-messages';
import {
  listStrategies,
  type ConditionInfoOut,
  type ConditionRefOut,
  type StrategyOut,
  type StrategySummary,
} from './generated';
import { isStrategySlug } from '@/lib/scan/params';

/**
 * Server-only read of the strategy list (GET /strategies). Callers import this instead of the
 * generated SDK; the write calls are kept apart (`strategies-write.ts`). Every failure becomes one of the
 * fixed messages in `strategies-messages.ts`; the API's own error text is never passed on. Names
 * and descriptions are user text: render them as escaped text only.
 */

export type { ConditionInfoOut, ConditionRefOut, StrategyOut, StrategySummary };

export type StrategiesResult<T> =
  { success: true; data: T } | { success: false; error: string; status?: number };

/** The API caps names at 64; anything far beyond that is contract drift. */
const MAX_STRATEGY_NAME = 100;
const MAX_STRATEGIES = 500;

function isRecord(body: unknown): body is Record<string, unknown> {
  return typeof body === 'object' && body !== null;
}

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

/**
 * Only the fields the pages read are checked (slug, name, flags, tuning), so a new zone kind or
 * condition param in the API does not take the whole list down.
 */
function isStrategy(body: unknown): body is StrategyOut {
  return (
    isRecord(body) &&
    isStrategySlug(body.slug) &&
    typeof body.name === 'string' &&
    body.name.length <= MAX_STRATEGY_NAME &&
    isFiniteNumber(body.swing_length) &&
    isFiniteNumber(body.near_atr) &&
    typeof body.mtf === 'boolean' &&
    typeof body.builtin === 'boolean'
  );
}

/** Parses `Retry-After` (whole seconds); anything else is ignored. */
function parseRetryAfter(header: string | null | undefined): number | undefined {
  if (!header || !/^\d{1,6}$/.test(header)) return undefined;
  return Number(header);
}

/** Every strategy, built-ins first then stored ones by slug (the API's order). */
export async function fetchStrategies(): Promise<StrategiesResult<StrategyOut[]>> {
  let retryAfter: number | undefined;
  const result = await callBackend(async (client) => {
    const response = await listStrategies({ client });
    retryAfter = parseRetryAfter(response.response?.headers.get('Retry-After'));
    return response;
  });
  if (!result.success) {
    return {
      success: false,
      error: strategiesErrorMessage({ status: result.status, retryAfter }),
      status: result.status,
    };
  }
  const items: unknown = isRecord(result.data) ? result.data.items : null;
  // A partly invalid list must not read as fewer strategies (the schedule list would flag the
  // dropped one as deleted); treat contract drift as a failure.
  if (!Array.isArray(items) || items.length > MAX_STRATEGIES || !items.every(isStrategy)) {
    return { success: false, error: STRATEGIES_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: items };
}
