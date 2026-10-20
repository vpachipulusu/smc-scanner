/**
 * Fixed messages for the AI analysis of scan hits. No `server-only` here so presentational
 * components can import them. The API's own error text (provider messages, keys, traces) is never
 * passed on.
 */

export const ANALYSE_UNAVAILABLE_MESSAGE = 'The scanner API could not be reached.';
export const ANALYSE_UNAUTHORIZED_MESSAGE = 'The scanner API rejected the internal key.';
export const ANALYSE_INVALID_MESSAGE = 'The scan options are not valid. Check them and try again.';
export const ANALYSE_PROVIDER_FAILED_MESSAGE =
  'The AI provider could not analyse these hits. Please try again later.';
export const ANALYSE_DISABLED_MESSAGE =
  'AI analysis is not available. Check the provider key and the database of the scanner API.';
export const ANALYSE_FAILED_MESSAGE = 'The AI analysis failed. Please try again.';
export const ANALYSE_DISABLED_HINT =
  'AI analysis is disabled: the scanner API has no AI provider key configured.';

/** Longest wait worth quoting; a longer Retry-After is shown as "later". */
const MAX_RETRY_SECONDS = 24 * 60 * 60;

/** Whole seconds from a `Retry-After` header; HTTP dates and junk give undefined. */
export function parseRetryAfter(value: string | null | undefined): number | undefined {
  if (value === null || value === undefined || !/^\d{1,9}$/.test(value.trim())) return undefined;
  const seconds = Number(value.trim());
  return seconds > 0 && seconds <= MAX_RETRY_SECONDS ? seconds : undefined;
}

function waitText(seconds: number): string {
  if (seconds < 60) return `${seconds} ${seconds === 1 ? 'second' : 'seconds'}`;
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`;
  const hours = Math.ceil(minutes / 60);
  return `${hours} ${hours === 1 ? 'hour' : 'hours'}`;
}

/** The friendly 429 text: the AI budget or rate limit was reached. */
export function rateLimitMessage(retryAfterSeconds?: number): string {
  const base = 'The AI analysis budget or rate limit has been reached.';
  return retryAfterSeconds === undefined
    ? `${base} Please try again later.`
    : `${base} Please try again in about ${waitText(retryAfterSeconds)}.`;
}

/** The message for a failed result. Never echoes the backend's text. */
export function analyseErrorMessage(result: {
  status?: number;
  retryAfterSeconds?: number;
}): string {
  switch (result.status) {
    case undefined:
      return ANALYSE_UNAVAILABLE_MESSAGE;
    case 401:
      return ANALYSE_UNAUTHORIZED_MESSAGE;
    case 422:
      return ANALYSE_INVALID_MESSAGE;
    case 429:
      return rateLimitMessage(result.retryAfterSeconds);
    case 502:
      return ANALYSE_PROVIDER_FAILED_MESSAGE;
    case 503:
      return ANALYSE_DISABLED_MESSAGE;
    default:
      return ANALYSE_FAILED_MESSAGE;
  }
}

export const NO_VERDICT_REASON = 'the AI provider returned no usable verdict';

/** What to say about one row the analyst did not give a verdict for; null when it has one. */
export function skipReason(status: string): string | null {
  switch (status) {
    case 'analysed':
      return null;
    case 'skipped_low_score':
      return 'below the score gate';
    case 'skipped_cap':
      return 'over the per-run limit';
    case 'skipped_duplicate':
      return 'already analysed on this bar';
    case 'skipped_failed_recently':
      return 'failed a moment ago, not retried yet';
    default:
      return NO_VERDICT_REASON;
  }
}
