import type { CumulativePointOut, JournalStatsOut, JournalStatsResponse } from '@/lib/api/journal';

import { NO_VALUE, formatR } from './format';

/** Types, response check and display helpers for the journal stats. Nothing here shows NaN. */

export type JournalStatsSummary = JournalStatsOut;
export type CumulativePoint = CumulativePointOut;
export type JournalStats = JournalStatsResponse;

const isRecord = (body: unknown): body is Record<string, unknown> =>
  typeof body === 'object' && body !== null;
const isNumber = (value: unknown): value is number => typeof value === 'number';
const isNullableNumber = (value: unknown): boolean => value === null || isNumber(value);

const COUNT_KEYS = ['closed_trades', 'open_trades', 'wins', 'losses', 'breakeven', 'total_r'];
const RATIO_KEYS = ['win_rate', 'average_r', 'avg_win_r', 'avg_loss_r', 'expectancy'];

function isSummary(body: unknown): boolean {
  return (
    isRecord(body) &&
    COUNT_KEYS.every((key) => isNumber(body[key])) &&
    RATIO_KEYS.every((key) => isNullableNumber(body[key]))
  );
}

function isPoint(body: unknown): body is CumulativePoint {
  return (
    isRecord(body) &&
    isNumber(body.entry_id) &&
    typeof body.closed_at === 'string' &&
    isNumber(body.r) &&
    isNumber(body.cumulative_r)
  );
}

/** True when the API body has the stats shape. One bad point fails the whole response. */
export function isStats(body: unknown): body is JournalStats {
  return (
    isRecord(body) &&
    isSummary(body.summary) &&
    Array.isArray(body.cumulative) &&
    body.cumulative.every(isPoint)
  );
}

/** A 0..1 ratio as "50%" or "66.7%"; a dash when missing or not finite. */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_VALUE;
  return `${Math.round(value * 1000) / 10}%`;
}

/** R as "+2.00R"; a dash when missing or not finite. */
export function formatRValue(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_VALUE;
  return formatR(value);
}

/** A count as a whole number; a dash when not finite. */
export function formatCount(value: number): string {
  return Number.isFinite(value) ? String(value) : NO_VALUE;
}
