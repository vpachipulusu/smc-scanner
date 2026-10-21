/**
 * Fixed messages for failed journal requests. No `server-only` here so components and tests can
 * import them. The API's own error text is never passed on.
 */

export const JOURNAL_UNAVAILABLE_MESSAGE = 'The scanner API could not be reached.';
export const JOURNAL_UNAUTHORIZED_MESSAGE = 'The scanner API rejected the internal key.';
export const JOURNAL_NOT_FOUND_MESSAGE = 'That journal entry no longer exists.';
export const JOURNAL_LIMIT_MESSAGE = 'The journal is full. Delete an entry before adding another.';
export const JOURNAL_INVALID_MESSAGE = 'The API rejected these values. Check the form and retry.';
export const JOURNAL_RATE_LIMITED_MESSAGE = 'Too many requests. Try again shortly.';
export const JOURNAL_STORE_UNAVAILABLE_MESSAGE = 'The journal database is unavailable.';
export const JOURNAL_REQUEST_FAILED_MESSAGE = 'The journal request failed. Please try again.';

/** The message for a failed result. Never echoes the backend's text. */
export function journalErrorMessage(result: { status?: number }): string {
  switch (result.status) {
    case undefined:
      return JOURNAL_UNAVAILABLE_MESSAGE;
    case 401:
      return JOURNAL_UNAUTHORIZED_MESSAGE;
    case 404:
      return JOURNAL_NOT_FOUND_MESSAGE;
    case 409:
      return JOURNAL_LIMIT_MESSAGE;
    case 422:
      return JOURNAL_INVALID_MESSAGE;
    case 429:
      return JOURNAL_RATE_LIMITED_MESSAGE;
    case 503:
      return JOURNAL_STORE_UNAVAILABLE_MESSAGE;
    default:
      return JOURNAL_REQUEST_FAILED_MESSAGE;
  }
}
