import type { StatusPillVariant } from '@/components/ui/status-pill';
import type { CalendarEventOut, CalendarResponse } from '@/lib/api/calendar';

/** Display helpers for the economic calendar. Nothing here ever shows NaN or Infinity. */

export const NO_VALUE = '—';

/** How far back from `as_of` the API lists events. */
export const LOOKBACK_HOURS = 2;

/** Longest event title shown; the feed is third-party text and can be arbitrarily long. */
export const MAX_TITLE_LENGTH = 120;
const MAX_CURRENCY_LENGTH = 8;

type Risk = CalendarResponse['immediate_risk'];
type Status = CalendarResponse['calendar_status'];
type Impact = CalendarEventOut['impact'];

const RISK_LABELS: Record<Risk, string> = {
  none: 'No immediate news risk',
  elevated: 'Elevated news risk',
  high: 'High news risk',
};
const RISK_TONES: Record<Risk, StatusPillVariant> = {
  none: 'good',
  elevated: 'warn',
  high: 'crit',
};
const STATUS_LABELS: Record<Status, string> = {
  fresh: 'Calendar up to date',
  stale: 'Calendar data is stale',
  unavailable: 'Calendar unavailable',
};
const IMPACT_LABELS: Record<Impact, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  holiday: 'Holiday',
};
const IMPACT_TONES: Record<Impact, StatusPillVariant> = {
  high: 'crit',
  medium: 'warn',
  low: 'neutral',
  holiday: 'info',
};

export const riskLabel = (risk: Risk): string => RISK_LABELS[risk];
export const riskTone = (risk: Risk): StatusPillVariant => RISK_TONES[risk];
export const statusLabel = (status: Status): string => STATUS_LABELS[status];
export const impactLabel = (impact: Impact): string => IMPACT_LABELS[impact];
export const impactTone = (impact: Impact): StatusPillVariant => IMPACT_TONES[impact];

/** A released figure, trimmed of trailing zeros; a dash when the feed has none. */
export function formatFigure(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return NO_VALUE;
  return String(Number(value.toFixed(4)));
}

/** Control characters become spaces, invisible and bidi format characters are dropped, runs of whitespace collapse. */
function cleanText(text: string): string {
  return text
    .replace(/\p{Cc}+/gu, ' ')
    .replace(/\p{Cf}+/gu, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function clip(text: string, max: number): string {
  const chars = Array.from(text);
  return chars.length <= max
    ? text
    : `${chars
        .slice(0, max - 1)
        .join('')
        .trimEnd()}…`;
}

/** Third-party title as short plain text; a dash when nothing printable is left. */
export function formatTitle(title: string): string {
  const cleaned = cleanText(title);
  return cleaned ? clip(cleaned, MAX_TITLE_LENGTH) : NO_VALUE;
}

export function formatCurrency(currency: string): string {
  const cleaned = cleanText(currency);
  return cleaned ? clip(cleaned, MAX_CURRENCY_LENGTH) : NO_VALUE;
}
