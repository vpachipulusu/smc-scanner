/**
 * Fixed messages for failed backtest requests. No `server-only` here so components and tests can
 * import them. The API's own error text is only ever matched against its known fixed strings to
 * pick one of these messages; it is never passed on.
 */

export const BACKTESTS_UNAVAILABLE_MESSAGE = 'The scanner API could not be reached.';
export const BACKTESTS_UNAUTHORIZED_MESSAGE = 'The scanner API rejected the internal key.';
export const BACKTEST_NOT_FOUND_MESSAGE = 'That backtest no longer exists.';
export const BACKTEST_ALREADY_RUNNING_MESSAGE =
  'A backtest is already running. Wait for it to finish, then run again.';
export const BACKTEST_UNKNOWN_STRATEGY_MESSAGE = 'That strategy no longer exists.';
export const BACKTEST_TOO_LARGE_MESSAGE =
  'This backtest is too large. Use fewer symbols or bars, or a larger stride.';
export const BACKTEST_INVALID_MESSAGE = 'The API rejected these values. Check the form and retry.';
export const BACKTESTS_STORE_UNAVAILABLE_MESSAGE = 'The backtest database is unavailable.';
export const BACKTEST_STRATEGY_STORE_UNAVAILABLE_MESSAGE = 'The strategy database is unavailable.';
export const BACKTESTS_REQUEST_FAILED_MESSAGE = 'The backtest request failed. Please try again.';
export const BACKTESTS_RATE_LIMIT_FALLBACK_MESSAGE =
  'Too many backtest requests. Try again shortly.';

/** A failed run whose stored error is not one of the API's fixed values. */
export const BACKTEST_RUN_FAILED_MESSAGE = 'The backtest failed. See the server log.';

/** The API's fixed 422 bodies; any other 422 is a plain validation failure. */
const INVALID_REASONS: Readonly<Record<string, string>> = {
  'Unknown strategy': BACKTEST_UNKNOWN_STRATEGY_MESSAGE,
  'Backtest too large; use fewer symbols or bars, or a larger stride': BACKTEST_TOO_LARGE_MESSAGE,
};

/** The API's fixed 503 bodies. */
const UNAVAILABLE_REASONS: Readonly<Record<string, string>> = {
  'Strategy database unavailable': BACKTEST_STRATEGY_STORE_UNAVAILABLE_MESSAGE,
};

/** The fixed `error` values of a failed run (TRAD-46), shown in our own words. */
const RUN_ERRORS: Readonly<Record<string, string>> = {
  'Backtest failed; see the server log': BACKTEST_RUN_FAILED_MESSAGE,
  'No symbol could be loaded':
    'No symbol could be loaded. Check the data source (the MT5 terminal) and the symbols.',
  'Backtest interrupted by a server restart':
    'The backtest was interrupted by a server restart. Run it again.',
};

const MAX_RETRY_SECONDS = 86_400;

const lookup = (table: Readonly<Record<string, string>>, key: string | undefined) =>
  key !== undefined && Object.hasOwn(table, key) ? table[key] : undefined;

/** A whole number of seconds within a day, or undefined. */
export function validRetryAfter(seconds: number | undefined): number | undefined {
  if (
    seconds === undefined ||
    !Number.isInteger(seconds) ||
    seconds < 1 ||
    seconds > MAX_RETRY_SECONDS
  ) {
    return undefined;
  }
  return seconds;
}

/** The longest wait a `Retry-After` can impose on the badges or the run poll. */
export const MAX_BACKOFF_MS = 5 * 60_000;

/**
 * How long to wait after a refusal: the `Retry-After` (in seconds) capped at `MAX_BACKOFF_MS`, or
 * `fallbackMs` when it is missing, zero or invalid.
 */
export function retryDelayMs(retryAfterSeconds: number | undefined, fallbackMs: number): number {
  const usable =
    retryAfterSeconds !== undefined &&
    Number.isInteger(retryAfterSeconds) &&
    retryAfterSeconds >= 1;
  return usable ? Math.min(retryAfterSeconds * 1000, MAX_BACKOFF_MS) : fallbackMs;
}

export function backtestRateLimitMessage(retryAfterSeconds?: number): string {
  const seconds = validRetryAfter(retryAfterSeconds);
  if (seconds === undefined) return BACKTESTS_RATE_LIMIT_FALLBACK_MESSAGE;
  const unit = seconds === 1 ? 'second' : 'seconds';
  return `Too many backtest requests. Try again in ${seconds} ${unit}.`;
}

/** The message for a failed result. `reason` is the API's error text, used only for matching. */
export function backtestErrorMessage(result: {
  status?: number;
  retryAfter?: number;
  reason?: string;
}): string {
  switch (result.status) {
    case undefined:
      return BACKTESTS_UNAVAILABLE_MESSAGE;
    case 401:
      return BACKTESTS_UNAUTHORIZED_MESSAGE;
    case 404:
      return BACKTEST_NOT_FOUND_MESSAGE;
    case 409:
      return BACKTEST_ALREADY_RUNNING_MESSAGE;
    case 422:
      return lookup(INVALID_REASONS, result.reason) ?? BACKTEST_INVALID_MESSAGE;
    case 429:
      return backtestRateLimitMessage(result.retryAfter);
    case 503:
      return lookup(UNAVAILABLE_REASONS, result.reason) ?? BACKTESTS_STORE_UNAVAILABLE_MESSAGE;
    default:
      return BACKTESTS_REQUEST_FAILED_MESSAGE;
  }
}

/** The message for a failed run's stored `error`; anything unknown becomes the generic one. */
export function backtestRunErrorMessage(error: string | null | undefined): string {
  return lookup(RUN_ERRORS, error ?? undefined) ?? BACKTEST_RUN_FAILED_MESSAGE;
}
