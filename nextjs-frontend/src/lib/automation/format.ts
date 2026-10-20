import type { JobLogOut } from '@/lib/api/schedules';

const MAX_ERROR_LENGTH = 200;

/** "2026-10-20 14:03 UTC", or a dash when there is no time. Fixed zone so output is stable. */
export function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return '—';
  return `${new Date(time).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  return seconds < 60
    ? `${seconds.toFixed(1)} s`
    : `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

/**
 * The first line of a job-log error, shortened. The raw text can hold a stack trace, so only the
 * summary line is shown. Always render the result as escaped text, never as markup.
 */
export function summarizeError(error: string | null): string | null {
  if (!error) return null;
  const first = error.split(/\r?\n/).find((line) => line.trim() !== '');
  if (first === undefined) return null;
  const line = first.trim();
  return line.length > MAX_ERROR_LENGTH ? `${line.slice(0, MAX_ERROR_LENGTH)}…` : line;
}

export type LogStatusView = { label: string; variant: 'good' | 'warn' | 'crit' };

export const LOG_STATUS_VIEWS: Record<JobLogOut['status'], LogStatusView> = {
  success: { label: 'Success', variant: 'good' },
  skipped: { label: 'Skipped', variant: 'warn' },
  failed: { label: 'Failed', variant: 'crit' },
};

/** Cursor values go straight back to the API, so cap what a query string can carry. */
export const MAX_CURSOR_LENGTH = 64;
const CURSOR_PATTERN = /^[A-Za-z0-9_\-=.:~]{1,64}$/;

export function parseCursor(raw: string | string[] | undefined): string | undefined {
  if (typeof raw !== 'string' || !CURSOR_PATTERN.test(raw)) return undefined;
  return raw;
}
