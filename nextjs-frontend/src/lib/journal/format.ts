import type { JournalEntryOut } from '@/lib/api/journal';

/** Display and number helpers for the journal. Nothing here ever shows NaN or Infinity. */

export const NO_VALUE = '—';

/** A number as a plain decimal (no exponent), trimmed, so it round-trips through a text field. */
export function plainDecimal(value: number): string {
  return value
    .toFixed(12)
    .replace(/(\.\d*?)0+$/, '$1')
    .replace(/\.$/, '');
}

/**
 * Result of a closed trade in units of its initial risk (the API's own formula). Null while the
 * trade is open, or when the risk is zero or the result is not finite.
 */
export function rMultiple(entry: JournalEntryOut): number | null {
  if (entry.exit === null || entry.exit === undefined) return null;
  const risk = Math.abs(entry.entry - entry.stop);
  if (risk === 0) return null;
  const move = entry.side === 'long' ? entry.exit - entry.entry : entry.entry - entry.exit;
  const result = move / risk;
  return Number.isFinite(result) ? result : null;
}

/** "+2.00R", "-0.50R", "0.00R"; a dash for an open trade. */
export function formatR(value: number | null): string {
  if (value === null) return NO_VALUE;
  const text = value.toFixed(2);
  if (Number(text) === 0) return '0.00R';
  return `${value > 0 ? '+' : ''}${text}R`;
}
