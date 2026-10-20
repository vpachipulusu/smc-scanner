import { Download } from 'lucide-react';

import { MAX_EXPORT_ROWS } from '@/components/analyses/history/csv';
import { HistoryError } from '@/components/analyses/history/history-error';
import { HistoryFilters } from '@/components/analyses/history/history-filters';
import { HistoryPager } from '@/components/analyses/history/history-pager';
import { HistoryTable } from '@/components/analyses/history/history-table';
import {
  HISTORY_PAGE_SIZE,
  historyHref,
  parseHistoryParams,
  type HistoryParams,
  type RawHistoryParams,
} from '@/components/analyses/history/params';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { fetchAnalyses, type AnalysisPage } from '@/lib/api/analyses';

/** Reads stored analyses through the API on every request, so it is never prerendered. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'Analyses' };

type SearchParams = Promise<RawHistoryParams>;

export default async function AnalysesPage({ searchParams }: { searchParams: SearchParams }) {
  const params = parseHistoryParams(await searchParams);
  const result = await fetchAnalyses({
    symbol: params.symbol,
    action: params.action,
    minConfidence: params.minConfidence,
    cursor: params.cursor,
    limit: HISTORY_PAGE_SIZE,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Analyses</h1>
        <p className="text-muted-foreground">Past AI verdicts, newest first.</p>
      </div>

      <Card>
        <CardContent className="space-y-4 pt-6">
          <HistoryFilters params={params} />
          {result.success ? (
            <HistoryResults params={params} page={result.data} />
          ) : (
            <HistoryError message={result.error} retryHref={historyHref(params)} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function HistoryResults({ params, page }: { params: HistoryParams; page: AnalysisPage }) {
  if (page.items.length === 0) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground" data-testid="history-empty">
          {params.cursor
            ? 'No older analyses.'
            : 'No analyses match these filters yet. Run a scan with AI analysis to add some.'}
        </p>
        <HistoryPager params={params} nextCursor={null} />
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground" data-testid="history-summary">
          {`Showing ${page.items.length} ${page.items.length === 1 ? 'analysis' : 'analyses'}.`}
        </p>
        <p className="text-xs text-muted-foreground sm:ml-auto">
          {`The CSV has every row of this filter, newest first, up to ${MAX_EXPORT_ROWS}.`}
        </p>
        <Button variant="outline" asChild>
          {/* A plain anchor: a next/link click would fetch the CSV route as an RSC navigation. */}
          <a href={historyHref(params, '/analyses/export', false)} download>
            <Download aria-hidden="true" className="size-4" />
            Download CSV
          </a>
        </Button>
      </div>
      <HistoryTable items={page.items} />
      <HistoryPager params={params} nextCursor={page.next_cursor} />
    </div>
  );
}
