import type { JournalEntryOut } from '@/lib/api/journal';

import { rMultiple } from './format';

/** CSV of the journal: the entry's own fields plus its R, blank while the trade is open. */

/** The API's largest page. */
export const EXPORT_PAGE_SIZE = 100;
/** Pages fetched at most, so one request cannot read the whole table. */
export const MAX_EXPORT_PAGES = 100;

export const JOURNAL_CSV_COLUMNS = [
  'id',
  'symbol',
  'timeframe',
  'side',
  'entry',
  'stop',
  'exit',
  'r',
  'size',
  'pnl_currency',
  'opened_at',
  'closed_at',
  'analysis_id',
  'notes',
] as const;

// A cell starting with one of these would be run as a formula by a spreadsheet.
// Invisible leading characters and the full-width forms of the triggers are covered too.
const FORMULA_PREFIX = /^[\s​-‏⁠﻿\0]*[=+\-@＝＋－＠]|^[\t\r]/;

function cell(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : ''; // a minus sign is not a formula
  const raw = String(value); // a malformed API field can never throw here
  const text = FORMULA_PREFIX.test(raw) ? `'${raw}` : raw;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function row(entry: JournalEntryOut): string {
  return [
    entry.id,
    entry.symbol,
    entry.timeframe,
    entry.side,
    entry.entry,
    entry.stop,
    entry.exit,
    rMultiple(entry),
    entry.size,
    entry.pnl_currency,
    entry.opened_at,
    entry.closed_at,
    entry.analysis_id,
    entry.notes,
  ]
    .map(cell)
    .join(',');
}

export function entriesToCsv(entries: ReadonlyArray<JournalEntryOut>): string {
  return `${[JOURNAL_CSV_COLUMNS.join(','), ...entries.map(row)].join('\r\n')}\r\n`;
}

export function journalCsvFileName(at: Date): string {
  const stamp = at
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}Z$/, 'Z');
  return `smc-journal-${stamp}.csv`;
}
