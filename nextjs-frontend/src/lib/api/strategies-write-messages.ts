/**
 * Fixed messages for failed strategy requests. No `server-only` here so components and tests can
 * import them. The API's own error text is only ever matched against its known fixed strings to
 * pick one of these messages; it is never passed on.
 */

export const STRATEGIES_UNAVAILABLE_MESSAGE = 'The scanner API could not be reached.';
export const STRATEGIES_UNAUTHORIZED_MESSAGE = 'The scanner API rejected the internal key.';
export const STRATEGY_NOT_FOUND_MESSAGE = 'That strategy no longer exists.';
export const STRATEGY_SLUG_TAKEN_MESSAGE =
  'A strategy with this slug already exists. Choose another.';
export const STRATEGY_BUILTIN_MESSAGE =
  'Built-in strategies cannot be changed or deleted. Duplicate it to make your own version.';
export const STRATEGY_LIMIT_MESSAGE =
  'The strategy limit is reached (50 custom strategies). Delete one first.';
export const STRATEGY_CONFLICT_MESSAGE = 'The strategy could not be saved. Reload and try again.';
export const STRATEGY_INVALID_MESSAGE = 'The API rejected these values. Check the form and retry.';
export const STRATEGIES_STORE_UNAVAILABLE_MESSAGE = 'The strategy database is unavailable.';
export const STRATEGIES_REQUEST_FAILED_MESSAGE = 'The strategy request failed. Please try again.';
export const STRATEGIES_RATE_LIMIT_FALLBACK_MESSAGE =
  'Too many strategy requests. Try again shortly.';
export const CONDITIONS_UNAVAILABLE_MESSAGE =
  'The condition list could not be loaded, so strategies cannot be edited right now.';

/** The API's fixed 409 bodies (see the strategy routes); anything else is a generic conflict. */
const CONFLICTS: Readonly<Record<string, string>> = {
  'A strategy with this slug already exists': STRATEGY_SLUG_TAKEN_MESSAGE,
  'Built-in strategies cannot be changed': STRATEGY_BUILTIN_MESSAGE,
  'Strategy limit reached': STRATEGY_LIMIT_MESSAGE,
};

const MAX_RETRY_SECONDS = 86_400;

export function strategyRateLimitMessage(retryAfterSeconds?: number): string {
  if (
    retryAfterSeconds === undefined ||
    !Number.isInteger(retryAfterSeconds) ||
    retryAfterSeconds < 1 ||
    retryAfterSeconds > MAX_RETRY_SECONDS
  ) {
    return STRATEGIES_RATE_LIMIT_FALLBACK_MESSAGE;
  }
  const unit = retryAfterSeconds === 1 ? 'second' : 'seconds';
  return `Too many strategy requests. Try again in ${retryAfterSeconds} ${unit}.`;
}

/** The message for a failed result. `reason` is the API's error text, used only for matching. */
export function strategyErrorMessage(result: {
  status?: number;
  retryAfter?: number;
  reason?: string;
}): string {
  switch (result.status) {
    case undefined:
      return STRATEGIES_UNAVAILABLE_MESSAGE;
    case 401:
      return STRATEGIES_UNAUTHORIZED_MESSAGE;
    case 404:
      return STRATEGY_NOT_FOUND_MESSAGE;
    case 409:
      return (
        (result.reason !== undefined && Object.hasOwn(CONFLICTS, result.reason)
          ? CONFLICTS[result.reason]
          : undefined) ?? STRATEGY_CONFLICT_MESSAGE
      );
    case 422:
      return STRATEGY_INVALID_MESSAGE;
    case 429:
      return strategyRateLimitMessage(result.retryAfter);
    case 503:
      return STRATEGIES_STORE_UNAVAILABLE_MESSAGE;
    default:
      return STRATEGIES_REQUEST_FAILED_MESSAGE;
  }
}
