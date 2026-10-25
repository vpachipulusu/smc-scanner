/**
 * Fixed messages for failed strategy reads. No `server-only` here so components and tests can
 * import them. The API's own error text is never passed on.
 */

export const STRATEGIES_UNAVAILABLE_MESSAGE = 'The scanner API could not be reached.';
export const STRATEGIES_UNAUTHORIZED_MESSAGE = 'The scanner API rejected the internal key.';
export const STRATEGIES_STORE_UNAVAILABLE_MESSAGE = 'The strategy database is unavailable.';
export const STRATEGIES_REQUEST_FAILED_MESSAGE = 'The strategy request failed. Please try again.';
export const STRATEGIES_RATE_LIMITED_FALLBACK_MESSAGE =
  'Too many strategy requests. Try again shortly.';

const MAX_RETRY_SECONDS = 86_400;

export function strategiesRateLimitedMessage(retryAfterSeconds?: number): string {
  if (
    retryAfterSeconds === undefined ||
    !Number.isInteger(retryAfterSeconds) ||
    retryAfterSeconds < 1 ||
    retryAfterSeconds > MAX_RETRY_SECONDS
  ) {
    return STRATEGIES_RATE_LIMITED_FALLBACK_MESSAGE;
  }
  const unit = retryAfterSeconds === 1 ? 'second' : 'seconds';
  return `Too many strategy requests. Try again in ${retryAfterSeconds} ${unit}.`;
}

/** The message for a failed result. Never echoes the backend's text. */
export function strategiesErrorMessage(result: { status?: number; retryAfter?: number }): string {
  switch (result.status) {
    case undefined:
      return STRATEGIES_UNAVAILABLE_MESSAGE;
    case 401:
      return STRATEGIES_UNAUTHORIZED_MESSAGE;
    case 429:
      return strategiesRateLimitedMessage(result.retryAfter);
    case 503:
      return STRATEGIES_STORE_UNAVAILABLE_MESSAGE;
    default:
      return STRATEGIES_REQUEST_FAILED_MESSAGE;
  }
}
