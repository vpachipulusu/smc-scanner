import type { ScanRowOut } from '@/lib/api/scan';

/**
 * CSV with the same columns, order and boolean spelling as the CLI's `scan_results.csv`, so a
 * file downloaded from the page can be diffed against one written by `smc-scan`.
 */

export const CSV_COLUMNS = [
  'instrument',
  'status',
  'zone',
  'zone_low',
  'zone_high',
  'price',
  'dist_atr',
  'bias',
  'in_ote',
  'trendline_ok',
  'ob_fvg',
  'score',
  'zone_age',
  'prior_touches',
  'bar_time',
] as const satisfies ReadonlyArray<keyof ScanRowOut>;

// A cell starting with one of these would be run as a formula by a spreadsheet.
const FORMULA_PREFIX = /^[=+\-@\t\r]/;

// Only the CSV columns reach here; `strategy` and `conditions` are not columns (matches the CLI).
function cell(value: ScanRowOut[(typeof CSV_COLUMNS)[number]]): string {
  if (value == null) return '';
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  if (typeof value === 'number') return String(value); // a minus sign is not a formula
  const text = FORMULA_PREFIX.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function rowsToCsv(rows: ReadonlyArray<ScanRowOut>): string {
  const lines = [CSV_COLUMNS.join(',')];
  for (const row of rows) {
    lines.push(CSV_COLUMNS.map((column) => cell(row[column])).join(','));
  }
  return `${lines.join('\r\n')}\r\n`;
}

export function csvFileName(source: string, tf: string, at: Date): string {
  const stamp = at
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}Z$/, 'Z');
  return `smc-scan-${source}-${tf}-${stamp}.csv`;
}
