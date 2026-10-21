import { TIMEFRAMES } from '@/lib/scan/params';

/**
 * Multi-timeframe helpers. The API analyses a scan on its own timeframe plus the next higher and
 * next lower one (`neighbour_timeframes`); these mirror that order for display. Alignment is
 * informational: it is never part of the 0-4 score.
 */

export const NOT_APPLICABLE = 'n/a';

export type HtfBias = 'bullish' | 'bearish' | 'range';
export type HtfAlignment = 'aligned' | 'conflict' | 'range' | 'n/a';

function indexOfTimeframe(tf: string): number {
  return (TIMEFRAMES as readonly string[]).indexOf(tf);
}

/** The scan timeframe, then the higher and the lower neighbour when they exist. */
export function scanTimeframes(tf: string): string[] {
  const index = indexOfTimeframe(tf);
  if (index < 0) return [tf];
  const higher = TIMEFRAMES[index + 1];
  const lower = TIMEFRAMES[index - 1];
  return [tf, ...(higher ? [higher] : []), ...(lower ? [lower] : [])];
}

/** Only well-known timeframe names, so stored text never reaches the page. */
export function knownTimeframes(used: unknown): string[] {
  return Array.isArray(used)
    ? used.filter((tf): tf is string => typeof tf === 'string' && indexOfTimeframe(tf) >= 0)
    : [];
}

/** The used timeframe above `tf`, or null when there is none (e.g. on 1d). */
export function higherTimeframe(tf: string, used: unknown): string | null {
  const base = indexOfTimeframe(tf);
  if (base < 0) return null;
  return knownTimeframes(used).find((name) => indexOfTimeframe(name) > base) ?? null;
}

/** Whether the higher timeframe's bias confirms the hit's direction (from its zone label). */
export function htfAlignment(row: { zone: string; htf_bias?: HtfBias | null }): HtfAlignment {
  const { htf_bias: bias } = row;
  if (typeof row.zone !== 'string') return 'n/a';
  if (bias === 'range') return 'range';
  if (bias !== 'bullish' && bias !== 'bearish') return 'n/a';
  let direction: HtfBias | null = null;
  if (row.zone.startsWith('bull')) direction = 'bullish';
  else if (row.zone.startsWith('bear')) direction = 'bearish';
  if (direction === null) return 'n/a';
  return bias === direction ? 'aligned' : 'conflict';
}

const ALIGNMENT_LABELS: Record<HtfAlignment, string> = {
  aligned: 'Aligned',
  conflict: 'Against HTF',
  range: 'HTF range',
  'n/a': NOT_APPLICABLE,
};

export function htfAlignmentLabel(alignment: HtfAlignment): string {
  return ALIGNMENT_LABELS[alignment];
}
