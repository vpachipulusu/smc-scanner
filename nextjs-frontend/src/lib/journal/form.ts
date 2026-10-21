import { z } from 'zod';

import type { JournalEntryIn, JournalEntryOut } from '@/lib/api/journal';
import { SYMBOL_PATTERN } from '@/lib/scan/params';

import { plainDecimal } from './format';

/**
 * Parsing and validation of the journal form. Limits mirror the API (`JournalEntryIn`), so a bad
 * value is caught here with a per-field message before any request. Only the allow-listed keys
 * below are ever read from the submitted form; everything else is ignored.
 */

export const TIMEFRAMES = ['5m', '15m', '30m', '1h', '4h', '1d'] as const;
export const SIDES = ['long', 'short'] as const;

export const LIMITS = {
  notesMax: 2000,
  maxAmount: 1e12,
  minPrice: 1e-9,
  /** |entry - stop| / entry must be at least this. */
  minRelativeRisk: 1e-6,
  maxAnalysisId: 2_147_483_647,
} as const;

/** Plain decimals only: no exponents, hex, `NaN` or `Infinity` that `Number()` would also read. */
export const DECIMAL_PATTERN = /^-?\d{1,13}(?:\.\d{1,12})?$/;
export const ANALYSIS_ID_PATTERN = /^[1-9]\d{0,9}$/;
const DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;
const MAX_FIELD_LENGTH = 64;

export type JournalFieldName =
  | 'symbol'
  | 'timeframe'
  | 'side'
  | 'entry'
  | 'stop'
  | 'exit'
  | 'size'
  | 'pnl_currency'
  | 'opened_at'
  | 'closed_at'
  | 'notes'
  | 'analysis_id';

export const FIELD_NAMES: readonly JournalFieldName[] = [
  'symbol',
  'timeframe',
  'side',
  'entry',
  'stop',
  'exit',
  'size',
  'pnl_currency',
  'opened_at',
  'closed_at',
  'notes',
  'analysis_id',
];

export type JournalFieldErrors = Partial<Record<JournalFieldName, string>>;

/** What the form shows: every field as text. Times are UTC, `YYYY-MM-DDTHH:mm`. */
export type JournalFormValues = Record<JournalFieldName, string>;

export const EMPTY_JOURNAL_VALUES: JournalFormValues = {
  symbol: '',
  timeframe: '1h',
  side: 'long',
  entry: '',
  stop: '',
  exit: '',
  size: '',
  pnl_currency: '',
  opened_at: '',
  closed_at: '',
  notes: '',
  analysis_id: '',
};

export type ParsedJournal =
  | { ok: true; body: JournalEntryIn }
  | { ok: false; errors: JournalFieldErrors; values: JournalFormValues };

/** `YYYY-MM-DDTHH:mm` (UTC) for a stored timestamp; blank when there is none. */
function inputTime(value: string | null | undefined): string {
  if (!value) return '';
  const time = Date.parse(value);
  return Number.isNaN(time) ? '' : new Date(time).toISOString().slice(0, 16);
}

function inputNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : plainDecimal(value);
}

export function valuesFromEntry(entry: JournalEntryOut): JournalFormValues {
  return {
    symbol: entry.symbol,
    timeframe: entry.timeframe,
    side: entry.side,
    entry: inputNumber(entry.entry),
    stop: inputNumber(entry.stop),
    exit: inputNumber(entry.exit),
    size: inputNumber(entry.size),
    pnl_currency: inputNumber(entry.pnl_currency),
    opened_at: inputTime(entry.opened_at),
    closed_at: inputTime(entry.closed_at),
    notes: entry.notes ?? '',
    analysis_id:
      entry.analysis_id === null || entry.analysis_id === undefined
        ? ''
        : String(entry.analysis_id),
  };
}

function text(form: FormData, key: JournalFieldName): string {
  const value = form.get(key);
  if (typeof value !== 'string') return '';
  // One character past the limit, so an over-long note fails validation instead of being cut.
  const limit = key === 'notes' ? LIMITS.notesMax + 1 : MAX_FIELD_LENGTH;
  return value.slice(0, limit).trim();
}

/** The submitted values as the form should show them again after an error. */
export function readJournalValues(form: FormData): JournalFormValues {
  const values = { ...EMPTY_JOURNAL_VALUES };
  for (const name of FIELD_NAMES) values[name] = text(form, name);
  return values;
}

const PRICE_MESSAGE = 'Enter a price above 0 as a plain number.';
const price = z
  .string()
  .regex(DECIMAL_PATTERN, PRICE_MESSAGE)
  .transform(Number)
  .pipe(z.number().min(LIMITS.minPrice, PRICE_MESSAGE).max(LIMITS.maxAmount, PRICE_MESSAGE));

const SIZE_MESSAGE = 'Enter a size above 0 as a plain number.';
const size = z
  .string()
  .regex(DECIMAL_PATTERN, SIZE_MESSAGE)
  .transform(Number)
  .pipe(z.number().gt(0, SIZE_MESSAGE).max(LIMITS.maxAmount, SIZE_MESSAGE));

const MONEY_MESSAGE = 'Enter an amount as a plain number.';
const money = z
  .string()
  .regex(DECIMAL_PATTERN, MONEY_MESSAGE)
  .transform(Number)
  .pipe(z.number().min(-LIMITS.maxAmount, MONEY_MESSAGE).max(LIMITS.maxAmount, MONEY_MESSAGE));

const TIME_MESSAGE = 'Enter a valid date and time (UTC).';
const time = z
  .string()
  .regex(DATETIME_PATTERN, TIME_MESSAGE)
  .refine((value) => {
    const date = new Date(`${value}:00Z`);
    return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
  }, TIME_MESSAGE)
  .transform((value) => `${value}:00Z`);

/** An empty field means "not given"; anything else must satisfy the schema. */
const optional = <T extends z.ZodTypeAny>(schema: T) =>
  z.preprocess((value) => (value === '' ? null : value), schema.nullable());

const analysisId = z
  .string()
  .regex(ANALYSIS_ID_PATTERN, 'Enter a whole number of 1 or more.')
  .transform(Number)
  .pipe(z.number().max(LIMITS.maxAnalysisId, 'Enter a whole number of 1 or more.'));

const schema = z
  .object({
    symbol: z
      .string()
      .regex(SYMBOL_PATTERN, 'Use letters, digits and . _ # @ - only (32 characters at most).'),
    timeframe: z.enum(TIMEFRAMES, { errorMap: () => ({ message: 'Choose a timeframe.' }) }),
    side: z.enum(SIDES, { errorMap: () => ({ message: 'Choose long or short.' }) }),
    entry: price,
    stop: price,
    exit: optional(price),
    size: optional(size),
    pnl_currency: optional(money),
    opened_at: time,
    closed_at: optional(time),
    notes: z.string().max(LIMITS.notesMax, `Use at most ${LIMITS.notesMax} characters.`),
    analysis_id: optional(analysisId),
  })
  .superRefine((data, ctx) => {
    const issue = (path: JournalFieldName, message: string) =>
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: [path], message });

    if (data.side === 'long' && data.stop >= data.entry) {
      issue('stop', 'For a long trade the stop must be below the entry.');
    } else if (data.side === 'short' && data.stop <= data.entry) {
      issue('stop', 'For a short trade the stop must be above the entry.');
    } else if (Math.abs(data.entry - data.stop) < data.entry * LIMITS.minRelativeRisk) {
      issue('stop', 'The stop is too close to the entry.');
    }
    if (data.exit !== null && data.closed_at === null) {
      issue('closed_at', 'Enter the close time together with the exit price.');
    }
    if (data.exit === null && data.closed_at !== null) {
      issue('exit', 'Enter the exit price together with the close time.');
    }
    if (data.closed_at !== null && data.closed_at < data.opened_at) {
      issue('closed_at', 'The close time must not be before the open time.');
    }
    if (data.exit === null && data.pnl_currency !== null) {
      issue('pnl_currency', 'A result needs a closed trade: enter the exit price and close time.');
    }
  });

function isFieldName(path: unknown): path is JournalFieldName {
  return typeof path === 'string' && (FIELD_NAMES as readonly string[]).includes(path);
}

/** Validates a submitted form into the API body, or per-field errors plus the values. */
export function parseJournalForm(form: FormData): ParsedJournal {
  const values = readJournalValues(form);
  const parsed = schema.safeParse(values);
  if (parsed.success) {
    // Explicit nulls so an update clears optional fields the user emptied.
    return { ok: true, body: parsed.data };
  }
  const errors: JournalFieldErrors = {};
  for (const issue of parsed.error.issues) {
    const name = issue.path[0];
    if (isFieldName(name) && errors[name] === undefined) errors[name] = issue.message;
  }
  return { ok: false, errors, values };
}

/** A positive safe integer id from a form field or route segment; null for anything else. */
export function parseJournalId(raw: unknown): number | null {
  if (typeof raw !== 'string' || !/^[1-9]\d{0,15}$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) ? id : null;
}
