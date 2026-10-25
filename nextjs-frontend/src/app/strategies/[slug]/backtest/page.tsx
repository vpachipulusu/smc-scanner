import Link from 'next/link';
import { notFound } from 'next/navigation';

import { BacktestDetail } from '@/components/backtests/backtest-detail';
import { BacktestHistory } from '@/components/backtests/backtest-history';
import { BacktestRunForm } from '@/components/backtests/backtest-run-form';
import { VerdictBadge } from '@/components/backtests/verdict-badge';
import { ErrorBanner } from '@/components/dashboard/error-banner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  fetchBacktest,
  fetchBacktests,
  fetchLatestBacktest,
  type BacktestListItem,
  type BacktestResult,
  type BacktestOut,
} from '@/lib/api/backtests';
import { BACKTEST_NOT_FOUND_MESSAGE } from '@/lib/api/backtests-messages';
import { fetchStrategy } from '@/lib/api/strategies-write';
import { backtestHref, parseRunId } from '@/lib/backtests/routes';
import { VERDICT_DESCRIPTIONS, badgeVerdict, type VerdictKey } from '@/lib/backtests/verdict';
import { SLUG_PATTERN } from '@/lib/strategies/schema';

/** Runs change in the background, so the page is always read live. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'Backtest' };

type Params = Promise<{ slug: string }>;
type SearchParams = Promise<{ run?: string | string[] }>;

/** History rows read for the page (newest first). */
const HISTORY_LIMIT = 50;

const inFlight = (item: BacktestListItem): boolean =>
  item.status === 'pending' || item.status === 'running';

/** The run to show: the one asked for, else the latest finished, else the latest of any kind. */
function pickRun(items: readonly BacktestListItem[], requested: number | null): number | null {
  if (requested !== null) return requested;
  return (items.find((item) => item.status === 'done') ?? items[0])?.id ?? null;
}

/**
 * The header badge, read afresh (not from the badge cache, which can lag a run that just ended):
 * the listed latest finished run, else the API's when the list may be cut short or failed. The
 * API is only asked once the strategy is known to exist.
 */
async function headerVerdict(
  list: BacktestResult<BacktestListItem[]>,
  strategyExists: boolean,
  slug: string
): Promise<VerdictKey | undefined> {
  const latestDone = list.success ? list.data.find((item) => item.status === 'done') : undefined;
  if (list.success && (latestDone || list.data.length < HISTORY_LIMIT)) {
    return badgeVerdict(latestDone ?? null);
  }
  if (!strategyExists) return undefined;
  const latest = await fetchLatestBacktest(slug);
  return latest.success ? badgeVerdict(latest.data) : undefined;
}

/** A run of another strategy is "not found" here. */
function forStrategy(
  result: BacktestResult<BacktestOut> | null,
  slug: string
): BacktestResult<BacktestOut> | null {
  if (result?.success && result.data.strategy !== slug) {
    return { success: false, error: BACKTEST_NOT_FOUND_MESSAGE, status: 404 };
  }
  return result;
}

export default async function BacktestPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const [{ slug }, { run }] = await Promise.all([params, searchParams]);
  if (!SLUG_PATTERN.test(slug)) notFound();
  const requested = parseRunId(run);
  // A run asked for by id is read alongside the list; otherwise the list picks it.
  const [strategy, list, requestedRun] = await Promise.all([
    fetchStrategy(slug),
    fetchBacktests(slug, HISTORY_LIMIT),
    requested === null ? null : fetchBacktest(requested),
  ]);
  if (!strategy.success && strategy.status === 404) notFound();

  const items = list.success ? list.data : [];
  const selectedId = pickRun(items, requested);
  const [selectedRun, verdict] = await Promise.all([
    requestedRun ?? (selectedId === null ? null : fetchBacktest(selectedId)),
    headerVerdict(list, strategy.success, slug),
  ]);
  const detail = forStrategy(selectedRun, slug);
  const name = strategy.success ? strategy.data.name : slug;
  const running = items.find(inFlight);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/strategies">Back to strategies</Link>
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold tracking-tight">Backtest: {name}</h1>
          {verdict && <VerdictBadge verdict={verdict} />}
        </div>
        <p className="text-muted-foreground">
          A walk-forward replay: the verdict judges the out-of-sample part against random entries
          and the flipped direction.
        </p>
      </div>

      {!strategy.success && <ErrorBanner message={strategy.error} />}
      {!list.success && (
        <div className="space-y-3">
          <ErrorBanner message={list.error} />
          <Button variant="outline" asChild>
            <Link href={backtestHref(slug)}>Retry</Link>
          </Button>
        </div>
      )}
      {list.success && items.length === 0 && (
        <p className="rounded-lg border p-3 text-sm" data-testid="not-run">
          {VERDICT_DESCRIPTIONS['not-run']} Run one below.
        </p>
      )}

      {detail && (
        <Card>
          <CardHeader>
            <h2 className="text-2xl font-semibold leading-none tracking-tight">Results</h2>
          </CardHeader>
          <CardContent>
            {detail.success ? (
              <BacktestDetail run={detail.data} />
            ) : (
              <ErrorBanner message={detail.error} />
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <h2 className="text-2xl font-semibold leading-none tracking-tight">Run backtest</h2>
        </CardHeader>
        <CardContent>
          <BacktestRunForm
            slug={slug}
            inFlightId={running?.id ?? null}
            inFlightStatus={running?.status}
          />
        </CardContent>
      </Card>

      {list.success && (
        <Card>
          <CardContent className="pt-6">
            <BacktestHistory
              slug={slug}
              items={items}
              selectedId={detail?.success ? detail.data.id : null}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
