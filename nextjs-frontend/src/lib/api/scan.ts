import 'server-only';

import { BACKEND_ERROR_MESSAGE, callBackend, type ApiResult } from './server';
import {
  config,
  scan,
  type ConfigResponse,
  type ScanFailureOut,
  type ScanResponse,
  type ScanRowOut,
} from './generated';
import { DEFAULT_STRATEGY } from '@/lib/scan/params';

/**
 * Server-only calls to the scanner API. Callers import these instead of the generated SDK. The
 * API's 422 and 503 texts are short and curated, so they are shown as they are; every other
 * failure becomes a fixed message here.
 */

export type { ConfigResponse, ScanFailureOut, ScanResponse, ScanRowOut };

export type ScanSource = NonNullable<ScanResponse['source']>;
export type ScanTimeframe = NonNullable<ScanResponse['tf']>;

export type ScanQuery = {
  source: ScanSource;
  tf: ScanTimeframe;
  /** Empty means the API's watchlist for the source. */
  symbols: string[];
  bars: number;
  swing: number;
  near: number;
  allTouches: boolean;
  /** Add the neighbouring timeframes' context. */
  mtf: boolean;
  /** Drop hits the higher timeframe does not confirm; the API rejects it without `mtf`. */
  requireHtfAligned: boolean;
  /** Strategy slug; the API's default (`smc-default`) is left out of the request. */
  strategy: string;
};

export const SCAN_UNAVAILABLE_MESSAGE =
  'The scanner API could not be reached. Start it with `uv run uvicorn smc_scanner.api:app`.';
export const SCAN_UNAUTHORIZED_MESSAGE =
  'The scanner API rejected the internal key. BACKEND_INTERNAL_KEY must equal SMC_INTERNAL_KEY.';
export const SCAN_NOTHING_LOADED_MESSAGE =
  'No symbol could be loaded. Check the MT5 terminal and the scanner log.';
export const SCAN_REQUEST_FAILED_MESSAGE = 'The scan request failed. Please try again.';

const CURATED_STATUSES: ReadonlySet<number> = new Set([422, 503]);
const CURATED_MAX_LENGTH = 200;

/** The message to show for a failed result. */
export function scanErrorMessage(result: { error: string; status?: number }): string {
  const { status, error } = result;
  if (status === undefined) return SCAN_UNAVAILABLE_MESSAGE;
  if (status === 401) return SCAN_UNAUTHORIZED_MESSAGE;
  const curated =
    error !== '' && error !== BACKEND_ERROR_MESSAGE && error.length <= CURATED_MAX_LENGTH;
  if (CURATED_STATUSES.has(status) && curated) {
    return error;
  }
  if (status === 503) return SCAN_NOTHING_LOADED_MESSAGE;
  return SCAN_REQUEST_FAILED_MESSAGE;
}

function isScanResponse(body: unknown): body is ScanResponse {
  return (
    typeof body === 'object' &&
    body !== null &&
    Array.isArray((body as ScanResponse).rows) &&
    Array.isArray((body as ScanResponse).failures)
  );
}

export async function fetchScan(query: ScanQuery): Promise<ApiResult<ScanResponse>> {
  const result = await callBackend((client) =>
    scan({
      client,
      query: {
        source: query.source,
        tf: query.tf,
        symbols: query.symbols.length > 0 ? query.symbols.join(',') : undefined,
        bars: query.bars,
        swing: query.swing,
        near: query.near,
        all_touches: query.allTouches,
        mtf: query.mtf,
        require_htf_aligned: query.requireHtfAligned,
        strategy: query.strategy === DEFAULT_STRATEGY ? undefined : query.strategy,
      },
    })
  );
  if (!result.success) return result;
  if (!isScanResponse(result.data)) {
    return { success: false, error: SCAN_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: result.data };
}

export async function fetchScanConfig(): Promise<ApiResult<ConfigResponse>> {
  const result = await callBackend((client) => config({ client }));
  if (!result.success) return result;
  const body = result.data;
  if (!Array.isArray(body?.sources) || !Array.isArray(body?.timeframes)) {
    return { success: false, error: SCAN_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: body };
}
