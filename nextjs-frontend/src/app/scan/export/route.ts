import { NextResponse } from 'next/server';
import { fetchScan, scanErrorMessage } from '@/lib/api/scan';
import { csvFileName, rowsToCsv } from '@/lib/scan/csv';
import { parseScanParams } from '@/lib/scan/params';

/**
 * `GET /scan/export?...` runs the same scan as the page and returns it as CSV, so the download
 * also goes through the server-only wrapper (the browser never calls FastAPI).
 */

export const dynamic = 'force-dynamic';

/** An unreachable API is a 503 here; the API's own status is passed through otherwise. */
export function exportErrorStatus(status: number | undefined): number {
  return status === undefined ? 503 : status;
}

export async function GET(request: Request): Promise<Response> {
  const searchParams = new URL(request.url).searchParams;
  // getAll keeps repeated params in order, so the page and the CSV agree (first value wins).
  const raw = Object.fromEntries(
    [...searchParams.keys()].map((key) => [key, searchParams.getAll(key)])
  );
  const { query } = parseScanParams(raw);
  const result = await fetchScan(query);
  if (!result.success) {
    return NextResponse.json(
      { success: false, error: scanErrorMessage(result) },
      { status: exportErrorStatus(result.status), headers: { 'Cache-Control': 'no-store' } }
    );
  }
  return new NextResponse(rowsToCsv(result.data.rows), {
    status: 200,
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="${csvFileName(query.source, query.tf, new Date())}"`,
      'Cache-Control': 'no-store',
    },
  });
}
