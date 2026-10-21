import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';

import { ErrorBanner } from '@/components/dashboard/error-banner';
import { JournalForm } from '@/components/journal/journal-form';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { fetchJournalEntry } from '@/lib/api/journal';
import { parseJournalId, valuesFromEntry } from '@/lib/journal/form';

/** The entry is read live, so an edit never starts from a stale copy. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'Edit journal entry' };

type Props = { params: Promise<{ id: string }> };

export default async function EditJournalPage({ params }: Props) {
  const id = parseJournalId((await params).id);
  if (id === null) notFound();

  const result = await fetchJournalEntry(id);
  if (!result.success && result.status === 404) notFound();

  return (
    <div className="space-y-6">
      <Link
        href="/journal"
        className="inline-flex min-h-10 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Back to journal
      </Link>
      <h1 className="text-3xl font-bold tracking-tight">Edit entry</h1>
      {result.success ? (
        <Card>
          <CardContent className="pt-6">
            <JournalForm
              key={`${result.data.id}-${result.data.updated_at}`}
              initialValues={valuesFromEntry(result.data)}
              entryId={result.data.id}
            />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          <ErrorBanner message={result.error} />
          <Button variant="outline" asChild>
            <Link href={`/journal/${id}/edit`}>Retry</Link>
          </Button>
        </div>
      )}
    </div>
  );
}
