'use server';

import { sendTestMessage } from '@/lib/api/telegram';
import {
  TELEGRAM_INVALID_MESSAGE,
  TELEGRAM_REQUEST_FAILED_MESSAGE,
  TELEGRAM_SENT_MESSAGE,
} from '@/lib/api/telegram-messages';
import { CHAT_ID_PATTERN } from '@/lib/automation/form';
import type { RowState } from '@/lib/automation/state';

/**
 * The "Send test message" form. The optional chat id is validated here with the same pattern the
 * API uses; an empty one sends to the server's default chat. Only fixed messages come back.
 * The scanner has no user accounts: it is a single-operator app, so access is controlled where it
 * is deployed (private network or an access proxy) and by the backend's internal key and cooldown.
 */
export async function sendTestMessageAction(
  _previous: RowState,
  formData: FormData
): Promise<RowState> {
  const raw = formData.get('chat_id');
  const chatId = typeof raw === 'string' ? raw.trim() : '';
  if (chatId !== '' && !CHAT_ID_PATTERN.test(chatId)) {
    return { status: 'error', message: TELEGRAM_INVALID_MESSAGE };
  }
  try {
    const result = await sendTestMessage(chatId === '' ? null : chatId);
    if (!result.success) return { status: 'error', message: result.error };
  } catch {
    return { status: 'error', message: TELEGRAM_REQUEST_FAILED_MESSAGE };
  }
  return { status: 'success', message: TELEGRAM_SENT_MESSAGE };
}
