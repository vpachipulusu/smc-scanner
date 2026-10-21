import type { AnalysisOut } from '@/lib/api/analyses';
import { SYMBOL_PATTERN } from '@/lib/scan/params';

import {
  ANALYSIS_ID_PATTERN,
  DECIMAL_PATTERN,
  LIMITS,
  SIDES,
  TIMEFRAMES,
  type JournalFormValues,
} from './form';
import { plainDecimal } from './format';

/**
 * Prefilling the new-entry form from an analysis, through query params on `/journal/new`. The
 * params are untrusted: each one is checked and silently dropped when invalid.
 */

export const NEW_ENTRY_PATH = '/journal/new';

type RawPrefill = Record<string, string | string[] | undefined>;

function isFinitePrice(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** The link that opens the new-entry form with this analysis' symbol, timeframe, side and setup. */
export function buildLogTradeHref(analysis: AnalysisOut): string {
  const params = new URLSearchParams({ symbol: analysis.symbol, timeframe: analysis.tf });
  const verdict = analysis.verdict;
  if (verdict?.action === 'BUY') params.set('side', 'long');
  if (verdict?.action === 'SELL') params.set('side', 'short');
  if (isFinitePrice(verdict?.entry)) params.set('entry', plainDecimal(verdict.entry));
  if (isFinitePrice(verdict?.stop)) params.set('stop', plainDecimal(verdict.stop));
  params.set('analysis_id', String(analysis.id));
  return `${NEW_ENTRY_PATH}?${params.toString()}`;
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function validPrice(value: string | undefined): value is string {
  return value !== undefined && DECIMAL_PATTERN.test(value) && Number(value) > 0;
}

/** The valid prefill values from the page's search params; everything else is ignored. */
export function parsePrefill(raw: RawPrefill): Partial<JournalFormValues> {
  const out: Partial<JournalFormValues> = {};
  const symbol = first(raw.symbol);
  const timeframe = first(raw.timeframe);
  const side = first(raw.side);
  const entry = first(raw.entry);
  const stop = first(raw.stop);
  const analysisId = first(raw.analysis_id);
  if (symbol !== undefined && SYMBOL_PATTERN.test(symbol)) out.symbol = symbol;
  if (timeframe !== undefined && (TIMEFRAMES as readonly string[]).includes(timeframe)) {
    out.timeframe = timeframe;
  }
  if (side !== undefined && (SIDES as readonly string[]).includes(side)) out.side = side;
  if (validPrice(entry)) out.entry = entry;
  if (validPrice(stop)) out.stop = stop;
  if (
    analysisId !== undefined &&
    ANALYSIS_ID_PATTERN.test(analysisId) &&
    Number(analysisId) <= LIMITS.maxAnalysisId
  ) {
    out.analysis_id = analysisId;
  }
  return out;
}
