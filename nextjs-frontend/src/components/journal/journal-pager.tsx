import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { journalHref } from '@/lib/journal/params';

/**
 * Keyset paging. The API only moves toward older entries (`next_cursor`), so the way back is the
 * newest page; the browser's back button steps one page at a time.
 */
export function JournalPager({
  cursor,
  nextCursor,
}: {
  cursor?: string;
  nextCursor: string | null | undefined;
}) {
  if (!cursor && !nextCursor) return null;

  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center gap-3">
      {cursor && (
        <Button variant="outline" asChild>
          <Link href={journalHref()}>Newest</Link>
        </Button>
      )}
      {nextCursor && (
        <Button variant="outline" asChild>
          <Link href={journalHref(nextCursor)}>Load more</Link>
        </Button>
      )}
    </nav>
  );
}
