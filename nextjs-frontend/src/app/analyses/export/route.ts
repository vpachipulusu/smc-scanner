import { NextResponse } from 'next/server';

import {
  EXPORT_PAGE_SIZE,
  MAX_EXPORT_PAGES,
  analysesCsvFileName,
  analysesToCsv,
} from '@/components/analyses/history/csv';
import { parseHistoryParams } from '@/components/analyses/history/params';
import { fetchAnalyses, type AnalysisOut } from '@/lib/api/analyses';

/**
 * `GET /analyses/export?...` returns the filtered view as CSV: the same filters as the page, from
 * the newest row, every page up to a cap. It goes through the server-only wrapper (the browser
 * never calls FastAPI).
 */

export const dynamic = 'force-dynamic';

/** An unreachable API is a 503; otherwise the API's own 4xx/5xx, never a stray 2xx or 3xx. */
function errorStatus(status: number | undefined): number {
  if (status === undefined) return 503;
  return status >= 400 && status <= 599 ? status : 502;
}

export async function GET(request: Request): Promise<Response> {
  const searchParams = new URL(request.url).searchParams;
  const raw = Object.fromEntries(
    [...searchParams.keys()].map((key) => [key, searchParams.getAll(key)])
  );
  const { symbol, action, minConfidence } = parseHistoryParams(raw);

  const items: AnalysisOut[] = [];
  let cursor: string | undefined;
  let truncated = false;
  for (let page = 1; page <= MAX_EXPORT_PAGES; page += 1) {
    const result = await fetchAnalyses({
      symbol,
      action,
      minConfidence,
      limit: EXPORT_PAGE_SIZE,
      cursor,
    });
    if (!result.success) {
      // Plain text: a download link saves or shows this, and a short sentence reads better than JSON.
      return new NextResponse(result.error, {
        status: errorStatus(result.status),
        headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' },
      });
    }
    items.push(...result.data.items);
    cursor = result.data.next_cursor ?? undefined;
    if (!cursor) break;
    truncated = page === MAX_EXPORT_PAGES;
  }

  const headers: Record<string, string> = {
    'Content-Type': 'text/csv; charset=utf-8',
    'Content-Disposition': `attachment; filename="${analysesCsvFileName(new Date())}"`,
    'Cache-Control': 'no-store',
  };
  if (truncated) headers['X-Export-Truncated'] = 'true';
  return new NextResponse(analysesToCsv(items), { status: 200, headers });
}
