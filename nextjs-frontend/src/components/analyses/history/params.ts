import type { AnalysisAction } from '@/lib/api/analyses';
import { SYMBOL_PATTERN, type Param } from '@/lib/scan/params';

/**
 * The history page and its CSV route read the same search params. Like the scan params, each one
 * falls back to "no filter" when missing or invalid, so a hand-edited URL never breaks the page.
 * Everything is checked against an allow-list or a pattern before it reaches the API.
 */

export const HISTORY_PAGE_SIZE = 25;

const ACTIONS: readonly AnalysisAction[] = ['BUY', 'SELL', 'HOLD'];

/** The API's cursors are urlsafe base64 and at most 64 characters. */
const CURSOR_PATTERN = /^[A-Za-z0-9_=-]{1,64}$/;

export type HistoryParams = {
  symbol?: string;
  action?: AnalysisAction;
  /** Percent, above 0 and at most 100. */
  minConfidence?: number;
  cursor?: string;
};

export type RawHistoryParams = Record<string, Param>;

/** First value of a repeated param; an empty string (a cleared form field) counts as absent. */
function first(value: Param): string | undefined {
  const single = Array.isArray(value) ? value[0] : value;
  return single === '' ? undefined : single;
}

function isAction(value: string): value is AnalysisAction {
  return ACTIONS.some((action) => action === value);
}

/** Plain decimals only: no exponents, hex or padding that `Number()` would also accept. */
const CONFIDENCE_PATTERN = /^\d{1,3}(\.\d{1,2})?$/;

function parseMinConfidence(value: string | undefined): number | undefined {
  if (value === undefined || !CONFIDENCE_PATTERN.test(value)) return undefined;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 && number <= 100 ? number : undefined;
}

export function parseHistoryParams(raw: RawHistoryParams): HistoryParams {
  const symbol = first(raw.symbol)?.trim();
  const action = first(raw.action)?.toUpperCase();
  const cursor = first(raw.cursor);
  const params: HistoryParams = {};
  if (symbol && SYMBOL_PATTERN.test(symbol)) params.symbol = symbol;
  if (action && isAction(action)) params.action = action;
  const minConfidence = parseMinConfidence(first(raw.min_conf));
  if (minConfidence !== undefined) params.minConfidence = minConfidence;
  if (cursor && CURSOR_PATTERN.test(cursor)) params.cursor = cursor;
  return params;
}

/** Query string for the page and the CSV route; the CSV route leaves the cursor out. */
export function historySearchParams(params: HistoryParams, withCursor = true): URLSearchParams {
  const out = new URLSearchParams();
  if (params.symbol) out.set('symbol', params.symbol);
  if (params.action) out.set('action', params.action);
  if (params.minConfidence !== undefined) out.set('min_conf', String(params.minConfidence));
  if (withCursor && params.cursor) out.set('cursor', params.cursor);
  return out;
}

export function historyHref(params: HistoryParams, path = '/analyses', withCursor = true): string {
  const qs = historySearchParams(params, withCursor).toString();
  return qs ? `${path}?${qs}` : path;
}
