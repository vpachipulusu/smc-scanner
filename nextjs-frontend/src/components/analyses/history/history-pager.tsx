import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { historyHref, type HistoryParams } from './params';

/**
 * Keyset paging. The API only moves toward older rows (`next_cursor`), so the way back is the
 * newest page; the browser's back button steps one page at a time.
 */
export function HistoryPager({
  params,
  nextCursor,
}: {
  params: HistoryParams;
  nextCursor: string | null | undefined;
}) {
  if (!params.cursor && !nextCursor) return null;

  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center gap-3">
      {params.cursor && (
        <Button variant="outline" asChild>
          <Link href={historyHref(params, '/analyses', false)}>Newest</Link>
        </Button>
      )}
      {nextCursor && (
        <Button variant="outline" asChild>
          <Link href={historyHref({ ...params, cursor: nextCursor })}>Older</Link>
        </Button>
      )}
    </nav>
  );
}
