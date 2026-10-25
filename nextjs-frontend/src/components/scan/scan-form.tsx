import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MtfOptions } from '@/components/scan/mtf-options';
import { StrategyFields } from '@/components/scan/strategy-fields';
import type { ConfigResponse } from '@/lib/api/scan';
import { LIMITS, SOURCES, TIMEFRAMES, scanHref, type ScanPageParams } from '@/lib/scan/params';
import type { StrategyOption } from '@/lib/scan/strategy-options';

/**
 * A GET form, like the orders filter: submitting navigates to `/scan?...` and the server runs the
 * scan, so the page works without JavaScript and every scan has a shareable URL. Choices come from
 * `GET /config` when the API answered, with the shared constants as the fallback.
 */

const SELECT_CLASSES =
  'h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';

export function ScanForm({
  params,
  config,
  strategies = [],
  strategiesComplete = true,
}: {
  params: ScanPageParams;
  config: ConfigResponse | null;
  /** Picker choices (see `strategyOptions`); empty keeps the current strategy as the only one. */
  strategies?: ReadonlyArray<StrategyOption>;
  /** False when only /config's built-ins loaded, so unknown slugs are not flagged as deleted. */
  strategiesComplete?: boolean;
}) {
  const { query, every } = params;
  const sources = config?.sources ?? SOURCES;
  const timeframes = config?.timeframes ?? TIMEFRAMES;
  const watchlist = config?.watchlist[query.source] ?? [];
  const symbolsPlaceholder =
    watchlist.length > 0 ? `watchlist: ${watchlist.join(', ')}` : 'watchlist (see watchlist.yaml)';
  const isDefault = scanHref(params) === '/scan';

  return (
    <form action="/scan" method="get" role="search" aria-label="Scan options" className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <Label htmlFor="scan-source" className="mb-1 block">
            Source
          </Label>
          <select
            id="scan-source"
            name="source"
            defaultValue={query.source}
            className={SELECT_CLASSES}
          >
            {sources.map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="scan-tf" className="mb-1 block">
            Timeframe
          </Label>
          <select id="scan-tf" name="tf" defaultValue={query.tf} className={SELECT_CLASSES}>
            {timeframes.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </div>
        <div className="sm:col-span-2">
          <Label htmlFor="scan-symbols" className="mb-1 block">
            Symbols
          </Label>
          <Input
            id="scan-symbols"
            name="symbols"
            defaultValue={query.symbols.join(', ')}
            placeholder={symbolsPlaceholder}
            autoComplete="off"
            spellCheck={false}
            aria-describedby="scan-symbols-hint"
          />
          <p id="scan-symbols-hint" className="mt-1 text-xs text-muted-foreground">
            Comma-separated, as Market Watch shows them; empty uses the watchlist.
          </p>
        </div>
        <div>
          <Label htmlFor="scan-bars" className="mb-1 block">
            Bars
          </Label>
          <Input
            id="scan-bars"
            name="bars"
            type="number"
            inputMode="numeric"
            min={LIMITS.minBars}
            max={LIMITS.maxBars}
            step={1}
            defaultValue={query.bars}
          />
        </div>
        <StrategyFields
          key={scanHref(params)}
          options={strategies}
          complete={strategiesComplete}
          strategy={query.strategy}
          swing={query.swing}
          near={query.near}
        />
        <div>
          <Label htmlFor="scan-every" className="mb-1 block">
            Rescan every (min)
          </Label>
          <Input
            id="scan-every"
            name="every"
            type="number"
            inputMode="numeric"
            min={0}
            max={LIMITS.maxEvery}
            step={1}
            defaultValue={every}
            aria-describedby="scan-every-hint"
          />
          <p id="scan-every-hint" className="mt-1 text-xs text-muted-foreground">
            0 scans once.
          </p>
        </div>
      </div>

      <MtfOptions
        key={scanHref(params)}
        idPrefix="scan"
        mtfName="mtf"
        requireName="htf"
        defaultMtf={query.mtf}
        defaultRequire={query.requireHtfAligned}
      />

      <div className="flex flex-wrap items-center gap-4">
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input
            type="checkbox"
            name="all"
            value="1"
            defaultChecked={query.allTouches}
            className="size-4 rounded border-input"
          />
          Include zones touched before
        </label>
        <div className="ml-auto flex gap-2">
          {!isDefault && (
            <Button variant="ghost" asChild>
              <Link href="/scan">Reset</Link>
            </Button>
          )}
          <Button type="submit">Scan</Button>
        </div>
      </div>
    </form>
  );
}
