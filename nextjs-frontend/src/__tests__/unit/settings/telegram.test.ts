// @vitest-environment node
/** The Telegram wrapper, its fixed messages and the test-message action. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { sendTestMessageAction } from '@/app/settings/actions';
import { sendTestMessage } from '@/lib/api/telegram';
import {
  TELEGRAM_COOLDOWN_MESSAGE,
  TELEGRAM_INVALID_MESSAGE,
  TELEGRAM_NOT_CONFIGURED_MESSAGE,
  TELEGRAM_REJECTED_MESSAGE,
  TELEGRAM_REQUEST_FAILED_MESSAGE,
  TELEGRAM_SENT_MESSAGE,
  TELEGRAM_UNAUTHORIZED_MESSAGE,
  TELEGRAM_UNAVAILABLE_MESSAGE,
} from '@/lib/api/telegram-messages';
import { IDLE_ROW_STATE } from '@/lib/automation/state';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('telegram test message', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it('posts the chat id and reports success', async () => {
    fetchMock.mockResolvedValue(json({ sent: true }));

    expect(await sendTestMessage('-1001234')).toEqual({ success: true });

    const request = fetchMock.mock.calls[0][0];
    expect(new URL(request.url).pathname).toBe('/telegram/test');
    expect(await request.json()).toEqual({ chat_id: '-1001234' });
  });

  it('sends no body for the default chat', async () => {
    fetchMock.mockResolvedValue(json({ sent: true }));

    await sendTestMessage(null);

    expect(await fetchMock.mock.calls[0][0].text()).toBe('');
  });

  it.each([
    [401, TELEGRAM_UNAUTHORIZED_MESSAGE],
    [422, TELEGRAM_INVALID_MESSAGE],
    [429, TELEGRAM_COOLDOWN_MESSAGE],
    [502, TELEGRAM_REJECTED_MESSAGE],
    [503, TELEGRAM_NOT_CONFIGURED_MESSAGE],
    [500, TELEGRAM_REQUEST_FAILED_MESSAGE],
  ])('maps %i to a fixed message and never echoes backend text', async (status, message) => {
    fetchMock.mockResolvedValue(json({ success: false, error: 'bot123:SECRET-token' }, status));

    const result = await sendTestMessage('42');

    expect(result).toEqual({ success: false, error: message });
    expect(JSON.stringify(result)).not.toContain('SECRET');
  });

  it('ignores a FastAPI detail body too', async () => {
    fetchMock.mockResolvedValue(json({ detail: 'bot123:SECRET-token' }, 502));

    const result = await sendTestMessage('42');

    expect(result).toEqual({ success: false, error: TELEGRAM_REJECTED_MESSAGE });
  });

  it('reports an unreachable API', async () => {
    fetchMock.mockRejectedValue(new Error('down'));
    expect(await sendTestMessage('42')).toEqual({
      success: false,
      error: TELEGRAM_UNAVAILABLE_MESSAGE,
    });
  });

  it('rejects an unexpected success body', async () => {
    fetchMock.mockResolvedValue(json({ nope: 1 }));
    expect(await sendTestMessage('42')).toEqual({
      success: false,
      error: TELEGRAM_REQUEST_FAILED_MESSAGE,
    });
  });

  describe('action', () => {
    const form = (chat?: string) => {
      const data = new FormData();
      if (chat !== undefined) data.set('chat_id', chat);
      return data;
    };

    it('rejects an invalid chat id without calling the API', async () => {
      expect(await sendTestMessageAction(IDLE_ROW_STATE, form('not a chat'))).toEqual({
        status: 'error',
        message: TELEGRAM_INVALID_MESSAGE,
      });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('sends to the default chat when empty and reports success', async () => {
      fetchMock.mockResolvedValue(json({ sent: true }));
      expect(await sendTestMessageAction(IDLE_ROW_STATE, form('  '))).toEqual({
        status: 'success',
        message: TELEGRAM_SENT_MESSAGE,
      });
    });

    it('accepts a channel name and surfaces a safe error', async () => {
      fetchMock.mockResolvedValue(json({ success: false, error: 'x' }, 502));
      expect(await sendTestMessageAction(IDLE_ROW_STATE, form('@mychannel'))).toEqual({
        status: 'error',
        message: TELEGRAM_REJECTED_MESSAGE,
      });
    });

    it('does not throw when the API cannot be reached', async () => {
      fetchMock.mockRejectedValue(new Error('boom'));
      const result = await sendTestMessageAction(IDLE_ROW_STATE, form('42'));
      expect(result).toEqual({ status: 'error', message: TELEGRAM_UNAVAILABLE_MESSAGE });
    });
  });
});
