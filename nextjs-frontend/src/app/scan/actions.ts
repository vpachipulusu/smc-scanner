'use server';

import { ANALYSE_FAILED_MESSAGE } from '@/lib/api/analyse-messages';
import { runAnalyse } from '@/lib/api/analyse';
import { parseScanParams, type RawScanParams } from '@/lib/scan/params';
import type { AnalyseState } from '@/lib/scan/analyse-state';

const FORM_KEYS = ['source', 'tf', 'symbols', 'bars', 'swing', 'near', 'all'] as const;
const MAX_FIELD_LENGTH = 2000;

/**
 * The "Analyse with AI" form: re-reads the scan options the form carries (hidden fields), runs
 * POST /analyse through the server-only wrapper and returns rows plus verdicts. The options go
 * through the same parser as the page, so a tampered field falls back to its default. Failures
 * come back as the wrapper's fixed messages only.
 */
export async function analyseScanAction(
  _previous: AnalyseState,
  formData: FormData
): Promise<AnalyseState> {
  const raw: RawScanParams = {};
  for (const key of FORM_KEYS) {
    const value = formData.get(key);
    if (typeof value === 'string') raw[key] = value.slice(0, MAX_FIELD_LENGTH);
  }
  const { query } = parseScanParams(raw);
  let result;
  try {
    result = await runAnalyse(query);
  } catch {
    return { status: 'error', message: ANALYSE_FAILED_MESSAGE };
  }
  if (!result.success) return { status: 'error', message: result.error };
  return { status: 'success', rows: result.data.rows, failures: result.data.failures };
}
