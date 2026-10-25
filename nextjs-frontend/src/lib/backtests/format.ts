import { NO_VALUE } from '@/lib/journal/format';
import { formatPercent, formatRValue } from '@/lib/journal/stats';

/** Display helpers for backtest figures. Nothing here shows NaN; missing values are a dash. */

export { NO_VALUE, formatPercent, formatRValue };

const isFiniteNumber = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value);

/** The 95% interval of the expectancy as "−0.12R to +0.40R". */
export function formatInterval(
  low: number | null | undefined,
  high: number | null | undefined
): string {
  if (!isFiniteNumber(low) || !isFiniteNumber(high)) return NO_VALUE;
  return `${formatRValue(low)} to ${formatRValue(high)}`;
}

/** Profit factor to two decimals; null with trades means there was no losing trade. */
export function formatProfitFactor(value: number | null | undefined, trades: number): string {
  if (isFiniteNumber(value)) return value.toFixed(2);
  return trades > 0 ? 'No losses' : NO_VALUE;
}

/** Max drawdown is a positive R in the API; shown as a loss. */
export function formatDrawdown(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return NO_VALUE;
  return value === 0 ? '0.00R' : `−${Math.abs(value).toFixed(2)}R`;
}

/** A plain number to at most `digits` decimals. */
export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (!isFiniteNumber(value)) return NO_VALUE;
  return String(Math.round(value * 10 ** digits) / 10 ** digits);
}

/** Seconds as "45 s", "3 min 05 s" or "1 h 02 min". */
export function formatDuration(seconds: number | null | undefined): string {
  if (!isFiniteNumber(seconds) || seconds < 0) return NO_VALUE;
  const total = Math.round(seconds);
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes} min ${String(total % 60).padStart(2, '0')} s`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`;
}

/** A large count in short scientific form, e.g. 120000000 as "1.2e8". */
export function formatCost(value: number): string {
  if (!Number.isFinite(value)) return NO_VALUE;
  if (value < 1e4) return String(Math.round(value));
  const [mantissa, exponent] = value.toExponential(1).split('e');
  return `${mantissa.replace(/\.0$/, '')}e${Number(exponent)}`;
}
