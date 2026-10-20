import type { AnalysisOut } from '@/lib/api/analyses';

/** CSV of the history table's columns, plus the id so a row can be traced back to its page. */

/** The API's largest page. */
export const EXPORT_PAGE_SIZE = 200;
/** Pages fetched at most, so one request cannot read the whole table. */
export const MAX_EXPORT_PAGES = 5;
export const MAX_EXPORT_ROWS = EXPORT_PAGE_SIZE * MAX_EXPORT_PAGES;

const HEADER = [
  'id',
  'time',
  'symbol',
  'tf',
  'action',
  'confidence',
  'quality',
  'zone',
  'provider',
];

// A cell starting with one of these would be run as a formula by a spreadsheet.
const FORMULA_PREFIX = /^\s*[=+\-@]|^[\t\r]/;

function cell(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return String(value); // a minus sign is not a formula
  const raw = String(value); // a malformed API field can never throw here
  const text = FORMULA_PREFIX.test(raw) ? `'${raw}` : raw;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function row(item: AnalysisOut): string {
  return [
    item.id,
    item.created_at,
    item.symbol,
    item.tf,
    item.verdict?.action,
    item.verdict?.confidence,
    item.verdict?.quality,
    item.zone,
    item.provider,
  ]
    .map(cell)
    .join(',');
}

export function analysesToCsv(items: ReadonlyArray<AnalysisOut>): string {
  return `${[HEADER.join(','), ...items.map(row)].join('\r\n')}\r\n`;
}

export function analysesCsvFileName(at: Date): string {
  const stamp = at
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}Z$/, 'Z');
  return `smc-analyses-${stamp}.csv`;
}
