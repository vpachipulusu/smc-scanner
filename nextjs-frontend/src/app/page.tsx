import { TriangleAlert } from 'lucide-react';

import { DashboardCard } from '@/components/dashboard/dashboard-card';
import { PlaceholderCard } from '@/components/dashboard/placeholder-card';
import { ScanFailures } from '@/components/scan/scan-failures';
import { StatusPill } from '@/components/ui/status-pill';
import type { ApiResult } from '@/lib/api/server';
import {
  fetchScan,
  SCAN_UNAVAILABLE_MESSAGE,
  scanErrorMessage,
  type ScanResponse,
} from '@/lib/api/scan';
import { DEFAULTS } from '@/lib/scan/params';

/** The scan reads live candles through the API, so the page is never prerendered. */
export const dynamic = 'force-dynamic';

async function loadScan(): Promise<ApiResult<ScanResponse>> {
  try {
    return await fetchScan(DEFAULTS);
  } catch {
    return { success: false, error: SCAN_UNAVAILABLE_MESSAGE };
  }
}

export default async function DashboardPage() {
  const result = await loadScan();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">Where the scanner stands right now.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {result.success ? (
          <>
            <TouchingCard rows={result.data.rows} />
            <SummaryCard response={result.data} />
          </>
        ) : (
          <ErrorBanner message={scanErrorMessage(result)} />
        )}
        <PlaceholderCard title="Latest verdicts" />
        <PlaceholderCard title="Next scheduled run" />
        <PlaceholderCard title="Last run status" />
      </div>
    </div>
  );
}

function TouchingCard({ rows }: { rows: ScanResponse['rows'] }) {
  const touching = rows.filter((row) => row.status === 'TOUCHING');
  return (
    <DashboardCard title="TOUCHING now">
      {touching.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No instrument is touching a fresh zone right now.
        </p>
      ) : (
        <ul className="divide-y">
          {touching.map((row) => (
            <li
              key={`${row.instrument}-${row.zone}-${row.bar_time}`}
              className="flex flex-wrap items-center gap-3 py-2"
            >
              <span className="min-w-20 font-medium">{row.instrument}</span>
              <StatusPill variant="good">TOUCHING</StatusPill>
              <span className="text-sm text-muted-foreground">{row.zone}</span>
            </li>
          ))}
        </ul>
      )}
    </DashboardCard>
  );
}

function SummaryCard({ response }: { response: ScanResponse }) {
  const total = response.rows.length;
  const near = response.rows.filter((row) => row.status === 'NEAR').length;
  const touching = response.rows.filter((row) => row.status === 'TOUCHING').length;
  return (
    <DashboardCard title="Latest scan summary">
      <div className="space-y-3">
        <p className="text-sm">
          {total} {total === 1 ? 'row' : 'rows'} on {response.tf} ({response.source}): {touching}{' '}
          touching, {near} near.
        </p>
        <ScanFailures failures={response.failures} />
      </div>
    </DashboardCard>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex items-center gap-2 rounded-lg border border-destructive/50 p-4 text-sm text-crit-foreground md:col-span-2"
    >
      <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />
      {message}
    </div>
  );
}
