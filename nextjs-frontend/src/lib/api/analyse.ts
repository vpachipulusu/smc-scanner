import 'server-only';

import { ANALYSE_FAILED_MESSAGE, analyseErrorMessage, parseRetryAfter } from './analyse-messages';
import { callBackend } from './server';
import {
  analyse,
  type AiResultOut,
  type AiVerdict,
  type AnalyseResponse,
  type AnalysedRowOut,
} from './generated';
import { SOURCES, TIMEFRAMES } from '@/lib/scan/params';
import type { ScanFailureOut, ScanQuery } from './scan';

/**
 * Server-only call to POST /analyse (scan, then the AI analyst over the hits). Callers import this
 * instead of the generated SDK. Every failure becomes one of the fixed messages in
 * `analyse-messages.ts`; the API's own error text is never passed on. A 429 also carries the
 * `Retry-After` seconds, which `callBackend` does not expose.
 */

export type { AiResultOut, AiVerdict, AnalyseResponse, AnalysedRowOut };

export type AnalyseResult =
  | { success: true; data: AnalyseResponse }
  | { success: false; error: string; status?: number; retryAfterSeconds?: number };

const ACTIONS: readonly unknown[] = ['BUY', 'SELL', 'HOLD'];
const STATUSES: readonly unknown[] = [
  'analysed',
  'skipped_low_score',
  'skipped_cap',
  'skipped_duplicate',
  'skipped_failed_recently',
  'failed',
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function finite(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/** A verdict with only well-typed fields, or null when action or confidence is unusable. */
function checkedVerdict(value: unknown): AiVerdict | null {
  if (!isRecord(value) || !ACTIONS.includes(value.action)) return null;
  const confidence = finite(value.confidence);
  if (confidence === undefined) return null;
  const targets = Array.isArray(value.targets)
    ? value.targets.filter((t): t is number => finite(t) !== undefined)
    : [];
  return {
    action: value.action as AiVerdict['action'],
    confidence,
    quality:
      value.quality === 'A' || value.quality === 'B' || value.quality === 'C'
        ? value.quality
        : null,
    entry: finite(value.entry) ?? null,
    stop: finite(value.stop) ?? null,
    targets,
    risk_reward: finite(value.risk_reward) ?? null,
  };
}

const ROW_STATUSES: readonly unknown[] = ['TOUCHING', 'NEAR'];
const BIASES: readonly unknown[] = ['bullish', 'bearish', 'range'];
const NUMBER_FIELDS = [
  'zone_low',
  'zone_high',
  'price',
  'dist_atr',
  'score',
  'zone_age',
  'prior_touches',
] as const;
const BOOLEAN_FIELDS = ['in_ote', 'trendline_ok', 'ob_fvg'] as const;
const MAX_FAILURE_TEXT = 200;

/**
 * The row rebuilt field by field from checked values (so unknown backend fields never reach the
 * browser). A row with a bad field is dropped; an unusable verdict becomes null; the free-text
 * note is blanked.
 */
function checkedRow(value: unknown): AnalysedRowOut | null {
  if (!isRecord(value) || !isRecord(value.ai)) return null;
  const { ai } = value;
  if (
    typeof value.instrument !== 'string' ||
    typeof value.zone !== 'string' ||
    typeof value.bar_time !== 'string' ||
    !ROW_STATUSES.includes(value.status) ||
    !BIASES.includes(value.bias) ||
    !STATUSES.includes(ai.status) ||
    NUMBER_FIELDS.some((key) => finite(value[key]) === undefined) ||
    BOOLEAN_FIELDS.some((key) => typeof value[key] !== 'boolean')
  ) {
    return null;
  }
  return {
    instrument: value.instrument,
    zone: value.zone,
    bar_time: value.bar_time,
    status: value.status as AnalysedRowOut['status'],
    bias: value.bias as AnalysedRowOut['bias'],
    zone_low: value.zone_low as number,
    zone_high: value.zone_high as number,
    price: value.price as number,
    dist_atr: value.dist_atr as number,
    score: value.score as number,
    zone_age: value.zone_age as number,
    prior_touches: value.prior_touches as number,
    in_ote: value.in_ote as boolean,
    trendline_ok: value.trendline_ok as boolean,
    ob_fvg: value.ob_fvg as boolean,
    ai: {
      status: ai.status as AiResultOut['status'],
      verdict: checkedVerdict(ai.verdict),
      note: '',
    },
  };
}

function checkedFailure(value: unknown): ScanFailureOut | null {
  if (!isRecord(value) || typeof value.symbol !== 'string' || typeof value.error !== 'string') {
    return null;
  }
  return { symbol: value.symbol, error: value.error.slice(0, MAX_FAILURE_TEXT) };
}

function checkedResponse(body: unknown): AnalyseResponse | null {
  if (!isRecord(body) || !Array.isArray(body.rows) || !Array.isArray(body.failures)) return null;
  if (
    !(SOURCES as readonly unknown[]).includes(body.source) ||
    !(TIMEFRAMES as readonly unknown[]).includes(body.tf)
  )
    return null;
  const rows = body.rows.map(checkedRow).filter((row): row is AnalysedRowOut => row !== null);
  const failures = body.failures
    .map(checkedFailure)
    .filter((failure): failure is ScanFailureOut => failure !== null);
  return {
    source: body.source as AnalyseResponse['source'],
    tf: body.tf as AnalyseResponse['tf'],
    count: rows.length,
    rows,
    failures,
  };
}

export async function runAnalyse(query: ScanQuery): Promise<AnalyseResult> {
  let response: Response | undefined;
  const result = await callBackend(async (client) => {
    const sdk = await analyse({
      client,
      body: {
        source: query.source,
        tf: query.tf,
        symbols: query.symbols.length > 0 ? query.symbols : null,
        bars: query.bars,
        swing: query.swing,
        near: query.near,
        all_touches: query.allTouches,
      },
    });
    response = sdk.response;
    return sdk;
  });
  if (!result.success) {
    const retryAfterSeconds =
      result.status === 429 ? parseRetryAfter(response?.headers.get('Retry-After')) : undefined;
    return {
      success: false,
      error: analyseErrorMessage({ status: result.status, retryAfterSeconds }),
      ...(result.status !== undefined && { status: result.status }),
      ...(retryAfterSeconds !== undefined && { retryAfterSeconds }),
    };
  }
  const data = checkedResponse(result.data);
  return data
    ? { success: true, data }
    : { success: false, error: ANALYSE_FAILED_MESSAGE, status: 502 };
}
