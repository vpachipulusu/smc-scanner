import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { AutoRefresh } from '@/components/scan/auto-refresh';
import { ScanAnalysis } from '@/components/scan/scan-analysis';
import { ScanFailures } from '@/components/scan/scan-failures';
import { ScanForm } from '@/components/scan/scan-form';
import { ScanLoadError } from '@/components/scan/scan-load-error';
import { fetchBacktestVerdicts } from '@/lib/api/backtests';
import { fetchScan, fetchScanConfig, scanErrorMessage, type ScanResponse } from '@/lib/api/scan';
import { fetchStrategies } from '@/lib/api/strategies';
import { aiAvailable } from '@/lib/scan/analyse-state';
import { conditionLabels, type ConditionLabels } from '@/lib/scan/conditions';
import {
  DEFAULT_STRATEGY,
  hasParam,
  parseScanParams,
  scanHref,
  withStrategyTuning,
  type RawScanParams,
  type ScanPageParams,
} from '@/lib/scan/params';
import { findStrategy, strategyOptions, type StrategyOption } from '@/lib/scan/strategy-options';

/** Every scan reads live candles through the API, so the page is never prerendered. */
export const dynamic = 'force-dynamic';

/** The AI analysis can take a minute; server actions inherit this limit. */
export const maxDuration = 60;

export const metadata = { title: 'Scan' };

type SearchParams = Promise<RawScanParams>;

/** A `/scan?strategy=` deep link without swing or near takes them from the strategy. */
function needsStrategyTuning(params: ScanPageParams, raw: RawScanParams): boolean {
  return (
    params.query.strategy !== DEFAULT_STRATEGY &&
    (!hasParam(raw, 'swing') || !hasParam(raw, 'near'))
  );
}

/** The params to scan with: a deep link's tuning comes from the strategy's validated summary. */
async function resolveParams(
  parsed: ScanPageParams,
  raw: RawScanParams,
  configPromise: ReturnType<typeof fetchScanConfig>
): Promise<ScanPageParams> {
  if (!needsStrategyTuning(parsed, raw)) return parsed;
  const result = await configPromise;
  const options = strategyOptions(result.success ? result.data : null, null);
  return withStrategyTuning(parsed, raw, findStrategy(options, parsed.query.strategy));
}

export default async function ScanPage({ searchParams }: { searchParams: SearchParams }) {
  const raw = await searchParams;
  const parsed = parseScanParams(raw);
  const configPromise = fetchScanConfig();
  // Only a deep link waits for /config before scanning; every other scan runs in parallel.
  const paramsPromise = resolveParams(parsed, raw, configPromise);
  const strategiesPromise = fetchStrategies();
  // The picker's verdict badges need only the strategy list, so they load beside the scan.
  const optionsPromise = Promise.all([configPromise, strategiesPromise]).then(([c, s]) =>
    strategyOptions(c.success ? c.data : null, s.success ? s.data : null)
  );
  const [configResult, strategiesResult, options, verdicts, [params, scanResult]] =
    await Promise.all([
      configPromise,
      strategiesPromise,
      optionsPromise,
      optionsPromise.then((list) => fetchBacktestVerdicts(list.map((option) => option.slug))),
      paramsPromise.then(async (resolved) => [resolved, await fetchScan(resolved.query)] as const),
    ]);
  const config = configResult.success ? configResult.data : null;
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
          <ScanForm
            params={params}
            config={config}
            strategies={options}
            strategiesComplete={strategiesResult.success}
            strategyVerdicts={verdicts}
          />
          <AutoRefresh
            everyMinutes={params.every}
            scannedAt={scannedAt}
            stopHref={scanHref({ ...params, every: 0 })}
          />
          {!scanResult.success ? (
            <ScanLoadError message={scanErrorMessage(scanResult)} retryHref={retryHref} />
          ) : (
            <ScanResults
              scanKey={`${retryHref}@${scannedAt}`}
              params={params}
              result={scanResult.data}
              aiEnabled={aiAvailable(config)}
              strategy={findStrategy(options, params.query.strategy)}
              labels={conditionLabels(config?.conditions)}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ScanResults({
  scanKey,
  params,
  result,
  aiEnabled,
  strategy,
  labels,
}: {
  scanKey: string;
  params: ScanPageParams;
  result: ScanResponse;
  aiEnabled: boolean;
  strategy: StrategyOption | undefined;
  labels: ConditionLabels;
}) {
  const { query } = params;
  const strategyNote =
    query.strategy === DEFAULT_STRATEGY ? '' : ` with ${strategy?.name ?? query.strategy}`;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground" data-testid="scan-summary">
          {result.count === 0
            ? `No instrument is touching or near a fresh zone on ${query.tf}${strategyNote}${query.requireHtfAligned ? ' that the higher timeframe confirms' : ''}.`
            : `${result.count} ${result.count === 1 ? 'hit' : 'hits'} on ${query.tf} (${query.source})${strategyNote}.`}
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
      {result.count > 0 ? (
        <ScanAnalysis
          key={scanKey}
          params={params}
          rows={result.rows}
          failures={result.failures}
          aiEnabled={aiEnabled}
          strategyMtf={strategy?.mtf ?? false}
          conditionLabels={labels}
        />
      ) : (
        <ScanFailures failures={result.failures} />
      )}
    </div>
  );
}
