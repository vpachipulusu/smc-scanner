import { ErrorBanner } from '@/components/dashboard/error-banner';
import {
  LATEST_VERDICTS_LIMIT,
  LatestVerdictsCard,
} from '@/components/dashboard/latest-verdicts-card';
import { PlaceholderCard } from '@/components/dashboard/placeholder-card';
import { SummaryCard, TouchingCard } from '@/components/dashboard/scan-cards';
import { fetchAnalyses, type AnalysisPage } from '@/lib/api/analyses';
import { analysesUnavailableMessage } from '@/lib/api/analyses-messages';
import {
  fetchScan,
  SCAN_UNAVAILABLE_MESSAGE,
  scanErrorMessage,
  type ScanResponse,
} from '@/lib/api/scan';
import type { ApiResult } from '@/lib/api/server';
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

async function loadAnalyses(): Promise<ApiResult<AnalysisPage>> {
  try {
    return await fetchAnalyses({ limit: LATEST_VERDICTS_LIMIT });
  } catch {
    return { success: false, error: analysesUnavailableMessage() };
  }
}

export default async function DashboardPage() {
  const [scanResult, analysesResult] = await Promise.all([loadScan(), loadAnalyses()]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">Where the scanner stands right now.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {scanResult.success ? (
          <>
            <TouchingCard rows={scanResult.data.rows} />
            <SummaryCard response={scanResult.data} />
          </>
        ) : (
          <ErrorBanner message={scanErrorMessage(scanResult)} className="md:col-span-2" />
        )}
        <LatestVerdictsCard result={analysesResult} />
        <PlaceholderCard title="Next scheduled run" />
        <PlaceholderCard title="Last run status" />
      </div>
    </div>
  );
}
