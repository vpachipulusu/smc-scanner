import 'server-only';

import { callBackend } from './server';
import { TELEGRAM_REQUEST_FAILED_MESSAGE, telegramErrorMessage } from './telegram-messages';
import { sendTelegramTest } from './generated';

/**
 * Server-only call to POST /telegram/test. Every failure becomes one of the fixed messages in
 * `telegram-messages.ts`; the API's own error text is never passed on.
 */

export type TelegramTestResult = { success: true } | { success: false; error: string };

/** `chatId` null or undefined sends to the server's default chat. */
export async function sendTestMessage(chatId?: string | null): Promise<TelegramTestResult> {
  const result = await callBackend((client) =>
    sendTelegramTest({ client, body: chatId ? { chat_id: chatId } : undefined })
  );
  if (!result.success) return { success: false, error: telegramErrorMessage(result) };
  const body: unknown = result.data;
  if (typeof body !== 'object' || body === null || (body as { sent?: unknown }).sent !== true) {
    return { success: false, error: TELEGRAM_REQUEST_FAILED_MESSAGE };
  }
  return { success: true };
}
