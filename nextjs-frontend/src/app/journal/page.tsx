import Link from 'next/link';
import { Download, Plus } from 'lucide-react';

import { ErrorBanner } from '@/components/dashboard/error-banner';
import { EquityCurve } from '@/components/journal/equity-curve';
import { JournalStatsCards } from '@/components/journal/journal-stats-cards';
import { JournalPager } from '@/components/journal/journal-pager';
import { JournalTable } from '@/components/journal/journal-table';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { fetchJournal, fetchJournalStats } from '@/lib/api/journal';
import { JOURNAL_HEADING_ID } from '@/lib/journal/ids';
import { JOURNAL_PAGE_SIZE, journalHref, parseJournalCursor } from '@/lib/journal/params';

/** The journal changes with every entry written here, so it is always read live. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'Journal' };

type SearchParams = Promise<{ cursor?: string | string[] }>;

export default async function JournalPage({ searchParams }: { searchParams: SearchParams }) {
  const cursor = parseJournalCursor((await searchParams).cursor);
  // /journal/stats is limited to 10 calls a minute: a failure there only shows its own banner.
  const [result, stats] = await Promise.all([
    fetchJournal({ limit: JOURNAL_PAGE_SIZE, cursor }),
    fetchJournalStats(),
  ]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1
            id={JOURNAL_HEADING_ID}
            tabIndex={-1}
            className="text-3xl font-bold tracking-tight outline-none"
          >
            Journal
          </h1>
          <p className="text-muted-foreground">Trades you logged by hand, newest first.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            {/* A plain link: a download, not a page, so it must not be prefetched. */}
            <a href="/journal/export">
              <Download aria-hidden="true" className="size-4" />
              Export CSV
            </a>
          </Button>
          <Button asChild>
            <Link href="/journal/new">
              <Plus aria-hidden="true" className="size-4" />
              New entry
            </Link>
          </Button>
        </div>
      </div>

      {stats.success ? (
        <>
          <JournalStatsCards summary={stats.data.summary} />
          {stats.data.cumulative.length > 0 && (
            <Card>
              <CardContent className="pt-6">
                <EquityCurve points={stats.data.cumulative} />
              </CardContent>
            </Card>
          )}
        </>
      ) : (
        <div className="space-y-3">
          <ErrorBanner message={stats.error} />
          <Button variant="outline" asChild>
            <Link href={journalHref(cursor)} aria-label="Retry loading statistics">
              Retry
            </Link>
          </Button>
        </div>
      )}

      <Card>
        <CardContent className="space-y-4 pt-6">
          {!result.success ? (
            <div className="space-y-3">
              <ErrorBanner message={result.error} />
              <Button variant="outline" asChild>
                <Link href={journalHref(cursor)} aria-label="Retry loading entries">
                  Retry
                </Link>
              </Button>
            </div>
          ) : result.data.items.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="journal-empty">
              {cursor
                ? 'No older entries.'
                : 'No trades logged yet. Add one with New entry, or use Log trade on an analysis.'}
            </p>
          ) : (
            <>
              <JournalTable entries={result.data.items} />
              <JournalPager cursor={cursor} nextCursor={result.data.next_cursor} />
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
