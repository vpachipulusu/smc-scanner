/**
 * Fixed messages for failed calendar requests. No `server-only` here so components and tests can
 * import them. The API's own error text is never passed on.
 */

export const CALENDAR_UNAVAILABLE_MESSAGE = 'The scanner API could not be reached.';
export const CALENDAR_UNAUTHORIZED_MESSAGE = 'The scanner API rejected the internal key.';
export const CALENDAR_INVALID_MESSAGE = 'The API rejected this symbol for the calendar.';
export const CALENDAR_RATE_LIMITED_MESSAGE = 'Too many requests. Try again shortly.';
export const CALENDAR_REQUEST_FAILED_MESSAGE = 'The calendar request failed. Please try again.';

/** The message for a failed result. Never echoes the backend's text. */
export function calendarErrorMessage(result: { status?: number }): string {
  switch (result.status) {
    case undefined:
      return CALENDAR_UNAVAILABLE_MESSAGE;
    case 401:
      return CALENDAR_UNAUTHORIZED_MESSAGE;
    case 422:
      return CALENDAR_INVALID_MESSAGE;
    case 429:
      return CALENDAR_RATE_LIMITED_MESSAGE;
    default:
      return CALENDAR_REQUEST_FAILED_MESSAGE;
  }
}
