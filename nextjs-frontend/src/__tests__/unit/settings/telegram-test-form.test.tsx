import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mocks = vi.hoisted(() => ({ action: vi.fn() }));
vi.mock('@/app/settings/actions', () => ({ sendTestMessageAction: mocks.action }));

import { TelegramTestForm } from '@/components/settings/telegram-test-form';

describe('TelegramTestForm', () => {
  beforeEach(() => mocks.action.mockReset());

  it('announces a success message', async () => {
    mocks.action.mockResolvedValue({ status: 'success', message: 'Test message sent.' });
    render(<TelegramTestForm configured />);

    await userEvent.type(screen.getByLabelText('Chat id (optional)'), '@mychannel');
    await userEvent.click(screen.getByRole('button', { name: 'Send test message' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Test message sent.');
    const data = mocks.action.mock.calls[0][1] as FormData;
    expect(data.get('chat_id')).toBe('@mychannel');
  });

  it('announces an error as an alert', async () => {
    mocks.action.mockResolvedValue({ status: 'error', message: 'Try again shortly.' });
    render(<TelegramTestForm configured />);

    await userEvent.click(screen.getByRole('button', { name: 'Send test message' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Error: Try again shortly.');
  });

  it('disables the button when Telegram is not configured', () => {
    render(<TelegramTestForm configured={false} />);

    expect(screen.getByRole('button', { name: 'Send test message' })).toBeDisabled();
    expect(screen.getByText(/Telegram is not configured/)).toBeInTheDocument();
  });
});
