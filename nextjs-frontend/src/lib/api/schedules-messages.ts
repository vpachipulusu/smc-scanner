/**
 * Fixed messages for failed schedule requests. No `server-only` here so components and tests can
 * import them. The API's own error text is never passed on.
 */

export const SCHEDULES_UNAVAILABLE_MESSAGE = 'The scanner API could not be reached.';
export const SCHEDULES_UNAUTHORIZED_MESSAGE = 'The scanner API rejected the internal key.';
export const SCHEDULE_NOT_FOUND_MESSAGE = 'That schedule no longer exists.';
export const SCHEDULE_INVALID_MESSAGE = 'The API rejected these values. Check the form and retry.';
export const SCHEDULES_STORE_UNAVAILABLE_MESSAGE = 'The schedule database is unavailable.';
export const SCHEDULE_BUSY_MESSAGE = 'A run is already in progress. Try again when it finishes.';
export const SCHEDULES_REQUEST_FAILED_MESSAGE = 'The schedule request failed. Please try again.';
export const SCHEDULE_COOLDOWN_FALLBACK_MESSAGE =
  'This schedule was run a moment ago. Try again shortly.';

const MAX_RETRY_SECONDS = 86_400;

export function scheduleCooldownMessage(retryAfterSeconds?: number): string {
  if (
    retryAfterSeconds === undefined ||
    !Number.isInteger(retryAfterSeconds) ||
    retryAfterSeconds < 1 ||
    retryAfterSeconds > MAX_RETRY_SECONDS
  ) {
    return SCHEDULE_COOLDOWN_FALLBACK_MESSAGE;
  }
  const unit = retryAfterSeconds === 1 ? 'second' : 'seconds';
  return `This schedule was run a moment ago. Try again in ${retryAfterSeconds} ${unit}.`;
}

/** The message for a failed result. Never echoes the backend's text. */
export function scheduleErrorMessage(result: { status?: number; retryAfter?: number }): string {
  switch (result.status) {
    case undefined:
      return SCHEDULES_UNAVAILABLE_MESSAGE;
    case 401:
      return SCHEDULES_UNAUTHORIZED_MESSAGE;
    case 404:
      return SCHEDULE_NOT_FOUND_MESSAGE;
    case 409:
      return SCHEDULE_BUSY_MESSAGE;
    case 422:
      return SCHEDULE_INVALID_MESSAGE;
    case 429:
      return scheduleCooldownMessage(result.retryAfter);
    case 503:
      return SCHEDULES_STORE_UNAVAILABLE_MESSAGE;
    default:
      return SCHEDULES_REQUEST_FAILED_MESSAGE;
  }
}
