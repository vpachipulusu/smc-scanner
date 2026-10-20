import 'server-only';

import { ANALYSES_REQUEST_FAILED_MESSAGE, analysesErrorMessage } from './analyses-messages';
import { callBackend, type ApiResult } from './server';
import {
  getAnalysis,
  listAnalyses,
  type AiVerdict,
  type AnalysisOut,
  type AnalysisPage,
} from './generated';

/**
 * Server-only reads of stored analyses. Callers import these instead of the generated SDK. Every
 * failure becomes one of the fixed messages in `analyses-messages.ts`; the API's own error text is
 * never passed on. Rows of a page that fail validation are dropped, the rest are kept.
 */

export type { AiVerdict, AnalysisOut, AnalysisPage };

export type AnalysisAction = NonNullable<AiVerdict['action']>;

export type AnalysesQuery = {
  symbol?: string;
  action?: AnalysisAction;
  minConfidence?: number;
  limit?: number;
  cursor?: string;
};

function isRecord(body: unknown): body is Record<string, unknown> {
  return typeof body === 'object' && body !== null;
}

const ACTIONS: readonly unknown[] = ['BUY', 'SELL', 'HOLD'];

function isVerdict(value: unknown): boolean {
  return (
    value === null ||
    (isRecord(value) && ACTIONS.includes(value.action) && typeof value.confidence === 'number')
  );
}

function isAnalysis(body: unknown): body is AnalysisOut {
  return (
    isRecord(body) &&
    typeof body.id === 'number' &&
    typeof body.symbol === 'string' &&
    typeof body.tf === 'string' &&
    typeof body.created_at === 'string' &&
    (body.status === 'ok' || body.status === 'failed') &&
    isVerdict(body.verdict)
  );
}

/** A page with its invalid rows dropped; null when the body is not a page at all. */
function validPage(body: unknown): AnalysisPage | null {
  if (!isRecord(body) || !Array.isArray(body.items)) return null;
  return { ...body, items: body.items.filter(isAnalysis) } as AnalysisPage;
}

function badBody(): { success: false; error: string; status: number } {
  return { success: false, error: ANALYSES_REQUEST_FAILED_MESSAGE, status: 502 };
}

/** One page of analyses, newest first. */
export async function fetchAnalyses(query: AnalysesQuery = {}): Promise<ApiResult<AnalysisPage>> {
  const result = await callBackend((client) =>
    listAnalyses({
      client,
      query: {
        symbol: query.symbol,
        action: query.action,
        min_confidence: query.minConfidence,
        limit: query.limit,
        cursor: query.cursor,
      },
    })
  );
  if (!result.success) return { ...result, error: analysesErrorMessage(result) };
  const page = validPage(result.data);
  return page ? { success: true, data: page } : badBody();
}

export async function fetchAnalysis(id: number): Promise<ApiResult<AnalysisOut>> {
  const result = await callBackend((client) => getAnalysis({ client, path: { analysis_id: id } }));
  if (!result.success) return { ...result, error: analysesErrorMessage(result) };
  return isAnalysis(result.data) ? { success: true, data: result.data } : badBody();
}
