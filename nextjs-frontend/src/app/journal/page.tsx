import Link from 'next/link';
import { Plus } from 'lucide-react';

import { ErrorBanner } from '@/components/dashboard/error-banner';
import { JournalPager } from '@/components/journal/journal-pager';
import { JournalTable } from '@/components/journal/journal-table';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { fetchJournal } from '@/lib/api/journal';
import { JOURNAL_HEADING_ID } from '@/lib/journal/ids';
import { JOURNAL_PAGE_SIZE, journalHref, parseJournalCursor } from '@/lib/journal/params';

/** The journal changes with every entry written here, so it is always read live. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'Journal' };

type SearchParams = Promise<{ cursor?: string | string[] }>;

export default async function JournalPage({ searchParams }: { searchParams: SearchParams }) {
  const cursor = parseJournalCursor((await searchParams).cursor);
  const result = await fetchJournal({ limit: JOURNAL_PAGE_SIZE, cursor });

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
        <Button asChild>
          <Link href="/journal/new">
            <Plus aria-hidden="true" className="size-4" />
            New entry
          </Link>
        </Button>
      </div>

      <Card>
        <CardContent className="space-y-4 pt-6">
          {!result.success ? (
            <div className="space-y-3">
              <ErrorBanner message={result.error} />
              <Button variant="outline" asChild>
                <Link href={journalHref(cursor)}>Retry</Link>
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
