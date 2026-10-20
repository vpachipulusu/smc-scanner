/**
 * Fixed messages for the Telegram test message. No `server-only` here so components and tests can
 * import them. The API's own error text is never passed on.
 */

export const TELEGRAM_SENT_MESSAGE = 'Test message sent. Check the chat.';
export const TELEGRAM_UNAVAILABLE_MESSAGE = 'The scanner API could not be reached.';
export const TELEGRAM_UNAUTHORIZED_MESSAGE = 'The scanner API rejected the internal key.';
export const TELEGRAM_INVALID_MESSAGE =
  'Use a numeric chat id (e.g. -1001234567890) or an @channelname, or set a default chat id on the server.';
export const TELEGRAM_COOLDOWN_MESSAGE = 'A test message was sent a moment ago. Try again shortly.';
export const TELEGRAM_NOT_CONFIGURED_MESSAGE =
  'Telegram is not configured on the server: TELEGRAM_BOT_TOKEN is not set.';
export const TELEGRAM_REJECTED_MESSAGE =
  'Telegram did not accept the message. Check the chat id and that the bot can post there.';
export const TELEGRAM_REQUEST_FAILED_MESSAGE = 'The test message failed. Please try again.';

/** The message for a failed result. Never echoes the backend's text. */
export function telegramErrorMessage(result: { status?: number }): string {
  switch (result.status) {
    case undefined:
      return TELEGRAM_UNAVAILABLE_MESSAGE;
    case 401:
      return TELEGRAM_UNAUTHORIZED_MESSAGE;
    case 422:
      return TELEGRAM_INVALID_MESSAGE;
    case 429:
      return TELEGRAM_COOLDOWN_MESSAGE;
    case 502:
      return TELEGRAM_REJECTED_MESSAGE;
    case 503:
      return TELEGRAM_NOT_CONFIGURED_MESSAGE;
    default:
      return TELEGRAM_REQUEST_FAILED_MESSAGE;
  }
}
