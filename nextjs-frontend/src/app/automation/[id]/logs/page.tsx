import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';

import { JobLogTable } from '@/components/automation/job-log-table';
import { ErrorBanner } from '@/components/dashboard/error-banner';
import { Button } from '@/components/ui/button';
import { fetchScheduleLogs } from '@/lib/api/schedules';
import { parseCursor } from '@/lib/automation/format';
import { parseScheduleId } from '@/lib/automation/form';

/** Runs append to the log at any time, so the page is always read live. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'Job log' };

const PAGE_SIZE = 50;

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ cursor?: string | string[] }>;
};

export default async function JobLogsPage({ params, searchParams }: Props) {
  const id = parseScheduleId((await params).id);
  if (id === null) notFound();
  const cursor = parseCursor((await searchParams).cursor);

  const result = await fetchScheduleLogs(id, { limit: PAGE_SIZE, cursor });
  if (!result.success && result.status === 404) notFound();

  return (
    <div className="space-y-6">
      <Link
        href="/automation"
        className="inline-flex min-h-10 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Back to automation
      </Link>
      <h1 className="text-3xl font-bold tracking-tight">Job log · schedule #{id}</h1>

      {!result.success ? (
        <div className="space-y-3">
          <ErrorBanner message={result.error} />
          <Button variant="outline" asChild>
            <Link href={`/automation/${id}/logs`}>Retry</Link>
          </Button>
        </div>
      ) : result.data.items.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="no-logs">
          No runs recorded yet.
        </p>
      ) : (
        <>
          <JobLogTable logs={result.data.items} />
          {result.data.next_cursor && (
            <Button variant="outline" asChild>
              <Link
                href={`/automation/${id}/logs?cursor=${encodeURIComponent(result.data.next_cursor)}`}
              >
                Older runs
              </Link>
            </Button>
          )}
        </>
      )}
    </div>
  );
}
