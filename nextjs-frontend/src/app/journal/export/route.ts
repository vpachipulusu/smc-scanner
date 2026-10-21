import { NextResponse } from 'next/server';

import { fetchJournal, type JournalEntryOut } from '@/lib/api/journal';
import {
  EXPORT_PAGE_SIZE,
  MAX_EXPORT_PAGES,
  entriesToCsv,
  journalCsvFileName,
} from '@/lib/journal/csv';

/**
 * `GET /journal/export` returns the whole journal as CSV, newest first, every page up to a cap. It
 * goes through the server-only wrapper (the browser never calls FastAPI). A failure on any page
 * is an error response, never a partial file.
 */

export const dynamic = 'force-dynamic';

/** An unreachable API is a 503; otherwise the API's own 4xx/5xx, never a stray 2xx or 3xx. */
function errorStatus(status: number | undefined): number {
  if (status === undefined) return 503;
  return status >= 400 && status <= 599 ? status : 502;
}

export async function GET(): Promise<Response> {
  const entries: JournalEntryOut[] = [];
  let cursor: string | undefined;
  let truncated = false;
  for (let page = 1; page <= MAX_EXPORT_PAGES; page += 1) {
    const result = await fetchJournal({ limit: EXPORT_PAGE_SIZE, cursor });
    if (!result.success) {
      // Plain text: a download link saves or shows this, and a short sentence reads better than JSON.
      return new NextResponse(result.error, {
        status: errorStatus(result.status),
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          'Cache-Control': 'no-store',
          'X-Content-Type-Options': 'nosniff',
        },
      });
    }
    entries.push(...result.data.items);
    cursor = result.data.next_cursor ?? undefined;
    if (!cursor) break;
    truncated = page === MAX_EXPORT_PAGES;
  }

  const headers: Record<string, string> = {
    'Content-Type': 'text/csv; charset=utf-8',
    'Content-Disposition': `attachment; filename="${journalCsvFileName(new Date())}"`,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  };
  if (truncated) headers['X-Export-Truncated'] = 'true';
  return new NextResponse(entriesToCsv(entries), { status: 200, headers });
}
