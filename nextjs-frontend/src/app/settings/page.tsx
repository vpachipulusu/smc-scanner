import { StatusRow } from '@/components/settings/status-row';
import { TelegramTestForm } from '@/components/settings/telegram-test-form';
import { ErrorBanner } from '@/components/dashboard/error-banner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { fetchScanConfig, scanErrorMessage } from '@/lib/api/scan';

/** Status reflects the server's environment, so it is always read live. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'Settings' };

export default async function SettingsPage() {
  const result = await fetchScanConfig();
  const config = result.success ? result.data : null;
  const aiEnabled = config?.ai_enabled === true;
  const telegramEnabled = config?.telegram_enabled === true;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Server configuration, read-only. Keys and tokens live in the server&apos;s environment and
          are never shown or edited here.
        </p>
      </div>

      {!result.success && <ErrorBanner message={scanErrorMessage(result)} />}

      <Card>
        <CardHeader>
          <CardTitle>Status</CardTitle>
        </CardHeader>
        <CardContent>
          {config ? (
            <dl>
              <StatusRow
                label="AI analysis"
                on={aiEnabled}
                onText="Configured"
                offText="Not configured"
              />
              <StatusRow
                label="Telegram alerts"
                on={telegramEnabled}
                onText="Configured"
                offText="Not configured"
              />
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">Status unavailable.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Telegram test message</CardTitle>
        </CardHeader>
        <CardContent>
          <TelegramTestForm configured={telegramEnabled} />
        </CardContent>
      </Card>
    </div>
  );
}
