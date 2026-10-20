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
 * Whether the API says an AI provider key is configured. `/config` does not carry the flag in
 * the generated client yet, so an absent or non-boolean `ai_enabled` counts as available and a
 * missing key surfaces as the fixed 503 message when the analysis is run.
 */
export function aiAvailable(config: ConfigResponse | null): boolean {
  const flag = config !== null && 'ai_enabled' in config ? config.ai_enabled : undefined;
  return flag !== false;
}
