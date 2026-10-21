import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

import { JournalForm } from '@/components/journal/journal-form';
import { Card, CardContent } from '@/components/ui/card';
import { EMPTY_JOURNAL_VALUES } from '@/lib/journal/form';
import { parsePrefill } from '@/lib/journal/prefill';

/** The opening time defaults to now, so the page is rendered per request. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'New journal entry' };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function NewJournalPage({ searchParams }: { searchParams: SearchParams }) {
  const initialValues = {
    ...EMPTY_JOURNAL_VALUES,
    opened_at: new Date().toISOString().slice(0, 16),
    ...parsePrefill(await searchParams),
  };

  return (
    <div className="space-y-6">
      <Link
        href="/journal"
        className="inline-flex min-h-10 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Back to journal
      </Link>
      <h1 className="text-3xl font-bold tracking-tight">Log a trade</h1>
      <Card>
        <CardContent className="pt-6">
          <JournalForm initialValues={initialValues} />
        </CardContent>
      </Card>
    </div>
  );
}
