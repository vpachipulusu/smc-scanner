import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

const mocks = vi.hoisted(() => ({ fetchScanConfig: vi.fn() }));
vi.mock('@/lib/api/scan', () => ({
  fetchScanConfig: mocks.fetchScanConfig,
  scanErrorMessage: (result: { error: string }) => result.error,
}));
vi.mock('@/app/settings/actions', () => ({ sendTestMessageAction: vi.fn() }));

import SettingsPage from '@/app/settings/page';

const config = (flags: { ai_enabled: boolean; telegram_enabled: boolean }) => ({
  success: true,
  data: { sources: ['demo'], timeframes: ['1h'], ...flags },
});

async function renderPage() {
  render(await SettingsPage());
}

describe('SettingsPage', () => {
  beforeEach(() => mocks.fetchScanConfig.mockReset());

  it('shows both services as configured and enables the test button', async () => {
    mocks.fetchScanConfig.mockResolvedValue(config({ ai_enabled: true, telegram_enabled: true }));
    await renderPage();

    expect(screen.getAllByText('Configured')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Send test message' })).toBeEnabled();
  });

  it('shows unconfigured services and disables the test button', async () => {
    mocks.fetchScanConfig.mockResolvedValue(config({ ai_enabled: false, telegram_enabled: false }));
    await renderPage();

    expect(screen.getAllByText('Not configured')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Send test message' })).toBeDisabled();
  });

  it('shows an error banner and unavailable status when the config cannot be loaded', async () => {
    mocks.fetchScanConfig.mockResolvedValue({ success: false, error: 'API down' });
    await renderPage();

    expect(screen.getByRole('alert')).toHaveTextContent('API down');
    expect(screen.getByText('Status unavailable.')).toBeInTheDocument();
  });
});
