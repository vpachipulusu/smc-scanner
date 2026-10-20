import type { AnalysedRowOut } from '@/lib/api/analyse';
import type { ConfigResponse, ScanFailureOut } from '@/lib/api/scan';

/**
 * The state the "Analyse with AI" form action hands back to the scan page. Kept out of the
 * `'use server'` module, which may only export async functions.
 */

export type AnalyseState =
  | { status: 'idle' }
  | { status: 'success'; rows: AnalysedRowOut[]; failures: ScanFailureOut[] }
  | { status: 'error'; message: string };

export const IDLE_ANALYSE_STATE: AnalyseState = { status: 'idle' };

/**
 * Whether the API says an AI provider key is configured. A config that could not be loaded
 * leaves the button enabled: a missing key then surfaces as the fixed 503 message on run.
 */
export function aiAvailable(config: ConfigResponse | null): boolean {
  return config === null || config.ai_enabled !== false;
}
