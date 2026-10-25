import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ErrorBanner } from '@/components/dashboard/error-banner';
import { StrategyForm } from '@/components/strategies/strategy-form';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { fetchConditionCatalogue, fetchStrategy } from '@/lib/api/strategies-write';
import { STRATEGY_BUILTIN_MESSAGE } from '@/lib/api/strategies-write-messages';
import { valuesFromStrategy } from '@/lib/strategies/form';
import { SLUG_PATTERN } from '@/lib/strategies/schema';

/** Edit a custom strategy. Built-ins are read-only: the page offers a duplicate instead. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'Edit strategy' };

type Params = Promise<{ slug: string }>;

export default async function EditStrategyPage({ params }: { params: Params }) {
  const { slug } = await params;
  if (!SLUG_PATTERN.test(slug)) notFound();
  const [result, catalogue] = await Promise.all([fetchStrategy(slug), fetchConditionCatalogue()]);
  if (!result.success && result.status === 404) notFound();

  const back = (
    <Button variant="outline" asChild>
      <Link href="/strategies">Back to strategies</Link>
    </Button>
  );

  if (!result.success || !catalogue.success) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold tracking-tight">Edit strategy</h1>
        <ErrorBanner
          message={!result.success ? result.error : catalogue.success ? '' : catalogue.error}
        />
        {back}
      </div>
    );
  }

  const strategy = result.data;
  if (strategy.builtin) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-bold tracking-tight">{strategy.name}</h1>
        <ErrorBanner message={STRATEGY_BUILTIN_MESSAGE} />
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link href={`/strategies/new?from=${encodeURIComponent(strategy.slug)}`}>
              Duplicate “{strategy.name}”
            </Link>
          </Button>
          {back}
        </div>
      </div>
    );
  }

  const known = new Set(catalogue.data.map((info) => info.key));
  const retired = [...strategy.require, ...strategy.score]
    .map((ref) => ref.key)
    .filter((key) => !known.has(key));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Edit “{strategy.name}”</h1>
        <p className="text-muted-foreground">Changes apply to the next scan and scheduled run.</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Definition</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {retired.length > 0 && (
            <p role="note" className="rounded-lg border p-3 text-sm">
              No longer available and dropped on save: {retired.join(', ')}.
            </p>
          )}
          <StrategyForm
            mode="edit"
            catalogue={catalogue.data}
            initial={valuesFromStrategy(strategy, catalogue.data)}
          />
        </CardContent>
      </Card>
    </div>
  );
}
