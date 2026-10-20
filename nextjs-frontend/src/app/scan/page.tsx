import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { AutoRefresh } from '@/components/scan/auto-refresh';
import { ScanFailures } from '@/components/scan/scan-failures';
import { ScanForm } from '@/components/scan/scan-form';
import { ScanLoadError } from '@/components/scan/scan-load-error';
import { ScanTable } from '@/components/scan/scan-table';
import { fetchScan, fetchScanConfig, scanErrorMessage, type ScanResponse } from '@/lib/api/scan';
import {
  parseScanParams,
  scanHref,
  type RawScanParams,
  type ScanPageParams,
} from '@/lib/scan/params';

/** Every scan reads live candles through the API, so the page is never prerendered. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'Scan' };

type SearchParams = Promise<RawScanParams>;

export default async function ScanPage({ searchParams }: { searchParams: SearchParams }) {
  const params = parseScanParams(await searchParams);
  const [configResult, scanResult] = await Promise.all([
    fetchScanConfig(),
    fetchScan(params.query),
  ]);
  const scannedAt = new Date().toISOString();
  const retryHref = scanHref(params);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Scan</h1>
        <p className="text-muted-foreground">
          Instruments whose latest candle is touching or near a fresh order block or fair value gap.
        </p>
      </div>

      <Card>
        <CardContent className="space-y-4 pt-6">
          <ScanForm params={params} config={configResult.success ? configResult.data : null} />
          <AutoRefresh
            everyMinutes={params.every}
            scannedAt={scannedAt}
            stopHref={scanHref({ ...params, every: 0 })}
          />
          {!scanResult.success ? (
            <ScanLoadError message={scanErrorMessage(scanResult)} retryHref={retryHref} />
          ) : (
            <ScanResults params={params} result={scanResult.data} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ScanResults({ params, result }: { params: ScanPageParams; result: ScanResponse }) {
  const { query } = params;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground" data-testid="scan-summary">
          {result.count === 0
            ? `No instrument is touching or near a fresh zone on ${query.tf}.`
            : `${result.count} ${result.count === 1 ? 'hit' : 'hits'} on ${query.tf} (${query.source}).`}
        </p>
        {result.count > 0 && (
          <Button variant="outline" asChild>
            {/* A plain anchor: a next/link click would fetch the CSV route as an RSC navigation first
                and run the scan twice. */}
            <a href={scanHref(params, '/scan/export')} download>
              <Download aria-hidden="true" className="size-4" />
              Download CSV
            </a>
          </Button>
        )}
      </div>
      {result.count > 0 && <ScanTable rows={result.rows} />}
      <ScanFailures failures={result.failures} />
    </div>
  );
}
