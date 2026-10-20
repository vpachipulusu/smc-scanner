import type { ScheduleCreate, ScheduleOut } from '@/lib/api/schedules';

/**
 * Parsing and validation of the schedule form. Limits mirror the API (`ScheduleCreate`), so a bad
 * value is caught here with a per-field message before any request. Only the allow-listed keys
 * below are ever read from the submitted form; everything else is ignored.
 */

export const SOURCES = ['mt5', 'demo'] as const;
export const TIMEFRAMES = ['5m', '15m', '30m', '1h', '4h', '1d'] as const;
export const FREQUENCIES = ['15m', '1h', '4h', '1d'] as const;

export const LIMITS = {
  nameMax: 64,
  symbolsMax: 50,
  minScoreMax: 4,
  minConfidenceMax: 100,
} as const;

export const DEFAULT_MIN_SCORE = 2;
export const MAX_FIELD_LENGTH = 2000;

const SYMBOL_PATTERN = /^[A-Za-z0-9._#@-]{1,32}$/;
const CHAT_ID_PATTERN = /^(?:-?[0-9]{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$/;
const INTEGER_PATTERN = /^\d{1,3}$/;
const DECIMAL_PATTERN = /^\d{1,3}(?:\.\d{1,4})?$/;
const SYMBOL_SEPARATOR = /[\s,;]+/;

export type FieldName =
  | 'name'
  | 'source'
  | 'tf'
  | 'symbols'
  | 'frequency'
  | 'min_score'
  | 'min_confidence'
  | 'telegram_chat_id';

export type FieldErrors = Partial<Record<FieldName, string>>;

/** What the form shows: strings for text-like fields, booleans for the switches. */
export type FormValues = {
  name: string;
  source: string;
  tf: string;
  symbols: string;
  frequency: string;
  min_score: string;
  min_confidence: string;
  only_on_change: boolean;
  send_hold: boolean;
  enabled: boolean;
  telegram_chat_id: string;
};

export const EMPTY_VALUES: FormValues = {
  name: '',
  source: 'mt5',
  tf: '1h',
  symbols: '',
  frequency: '1h',
  min_score: String(DEFAULT_MIN_SCORE),
  min_confidence: '0',
  only_on_change: false,
  send_hold: false,
  enabled: true,
  telegram_chat_id: '',
};

export type ParsedSchedule =
  { ok: true; body: ScheduleCreate } | { ok: false; errors: FieldErrors; values: FormValues };

export function valuesFromSchedule(schedule: ScheduleOut): FormValues {
  return {
    name: schedule.name,
    source: schedule.source,
    tf: schedule.tf,
    symbols: schedule.symbols.join(', '),
    frequency: schedule.frequency,
    min_score: String(schedule.min_score),
    min_confidence: String(schedule.min_confidence),
    only_on_change: schedule.only_on_change,
    send_hold: schedule.send_hold,
    enabled: schedule.enabled,
    telegram_chat_id: schedule.telegram_chat_id ?? '',
  };
}

function text(form: FormData, key: string): string {
  const value = form.get(key);
  return typeof value === 'string' ? value.slice(0, MAX_FIELD_LENGTH).trim() : '';
}

function flag(form: FormData, key: string): boolean {
  return form.get(key) === 'on';
}

/** The submitted values as the form should show them again after an error. */
export function readValues(form: FormData): FormValues {
  return {
    name: text(form, 'name'),
    source: text(form, 'source'),
    tf: text(form, 'tf'),
    symbols: text(form, 'symbols'),
    frequency: text(form, 'frequency'),
    min_score: text(form, 'min_score'),
    min_confidence: text(form, 'min_confidence'),
    only_on_change: flag(form, 'only_on_change'),
    send_hold: flag(form, 'send_hold'),
    enabled: flag(form, 'enabled'),
    telegram_chat_id: text(form, 'telegram_chat_id'),
  };
}

function oneOf<T extends string>(options: readonly T[], value: string): value is T {
  return (options as readonly string[]).includes(value);
}

export function parseSymbols(raw: string): string[] {
  const seen = new Set<string>();
  for (const symbol of raw.split(SYMBOL_SEPARATOR)) {
    if (symbol !== '') seen.add(symbol);
  }
  return [...seen];
}

function validateSymbols(raw: string): { symbols: string[]; error?: string } {
  const symbols = parseSymbols(raw);
  if (symbols.length === 0) return { symbols, error: 'Enter at least one symbol.' };
  if (symbols.length > LIMITS.symbolsMax) {
    return { symbols, error: `Use at most ${LIMITS.symbolsMax} symbols.` };
  }
  const bad = symbols.find((symbol) => !SYMBOL_PATTERN.test(symbol));
  if (bad !== undefined) {
    return {
      symbols,
      error: 'Symbols may use letters, digits and . _ # @ - only (32 characters at most).',
    };
  }
  return { symbols };
}

function parseBounded(raw: string, max: number, pattern: RegExp, fallback: number) {
  if (raw === '') return { value: fallback };
  if (!pattern.test(raw)) return { error: true as const };
  const value = Number(raw);
  return value <= max ? { value } : { error: true as const };
}

/** Validates a submitted form into the API's create body, or per-field errors plus the values. */
export function parseScheduleForm(form: FormData): ParsedSchedule {
  const values = readValues(form);
  const errors: FieldErrors = {};

  if (values.name === '') errors.name = 'Enter a name.';
  else if ([...values.name].length > LIMITS.nameMax) {
    errors.name = `Use at most ${LIMITS.nameMax} characters.`;
  }
  if (!oneOf(SOURCES, values.source)) errors.source = 'Choose a source.';
  if (!oneOf(TIMEFRAMES, values.tf)) errors.tf = 'Choose a timeframe.';
  if (!oneOf(FREQUENCIES, values.frequency)) errors.frequency = 'Choose a frequency.';

  const { symbols, error: symbolsError } = validateSymbols(values.symbols);
  if (symbolsError) errors.symbols = symbolsError;

  const score = parseBounded(
    values.min_score,
    LIMITS.minScoreMax,
    INTEGER_PATTERN,
    DEFAULT_MIN_SCORE
  );
  if ('error' in score) errors.min_score = `Enter a whole number from 0 to ${LIMITS.minScoreMax}.`;
  const confidence = parseBounded(
    values.min_confidence,
    LIMITS.minConfidenceMax,
    DECIMAL_PATTERN,
    0
  );
  if ('error' in confidence) {
    errors.min_confidence = `Enter a number from 0 to ${LIMITS.minConfidenceMax}.`;
  }

  const chatId = values.telegram_chat_id;
  if (chatId !== '' && !CHAT_ID_PATTERN.test(chatId)) {
    errors.telegram_chat_id = 'Use a numeric chat id (e.g. -1001234567890) or an @channelname.';
  }

  if (
    Object.keys(errors).length > 0 ||
    !oneOf(SOURCES, values.source) ||
    !oneOf(TIMEFRAMES, values.tf) ||
    !oneOf(FREQUENCIES, values.frequency) ||
    'error' in score ||
    'error' in confidence
  ) {
    return { ok: false, errors, values };
  }
  return {
    ok: true,
    body: {
      name: values.name,
      source: values.source,
      tf: values.tf,
      symbols,
      frequency: values.frequency,
      min_score: score.value,
      min_confidence: confidence.value,
      only_on_change: values.only_on_change,
      send_hold: values.send_hold,
      enabled: values.enabled,
      telegram_chat_id: chatId === '' ? null : chatId,
    },
  };
}

/** A positive safe integer id from a form field or route segment; null for anything else. */
export function parseScheduleId(raw: unknown): number | null {
  if (typeof raw !== 'string' || !/^[1-9]\d{0,15}$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) ? id : null;
}
