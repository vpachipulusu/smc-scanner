import Link from 'next/link';

import { ErrorBanner } from '@/components/dashboard/error-banner';
import { StrategyForm } from '@/components/strategies/strategy-form';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { fetchConditionCatalogue, fetchStrategies } from '@/lib/api/strategies-write';
import { STRATEGY_NOT_FOUND_MESSAGE } from '@/lib/api/strategies-write-messages';
import { duplicateValues, emptyFormValues } from '@/lib/strategies/form';
import { SLUG_PATTERN } from '@/lib/strategies/schema';

/** A new strategy, empty or (`?from=<slug>`) a copy of a built-in or custom one with a new slug. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'New strategy' };

type SearchParams = Promise<{ from?: string | string[] }>;

export default async function NewStrategyPage({ searchParams }: { searchParams: SearchParams }) {
  const { from } = await searchParams;
  const [list, catalogue] = await Promise.all([fetchStrategies(), fetchConditionCatalogue()]);
  const strategies = list.success ? list.data : [];
  const fromSlug = typeof from === 'string' && SLUG_PATTERN.test(from) ? from : null;
  const source = strategies.find((strategy) => strategy.slug === fromSlug);
  const staleSource = from !== undefined && list.success && source === undefined;

  const heading = (
    <div>
      <h1 className="text-3xl font-bold tracking-tight">
        {source ? `Duplicate “${source.name}”` : 'New strategy'}
      </h1>
      <p className="text-muted-foreground">
        Pick the zones to look for and which conditions each one must pass or scores on.
      </p>
    </div>
  );

  if (!list.success || !catalogue.success) {
    return (
      <div className="space-y-6">
        {heading}
        <ErrorBanner
          message={!list.success ? list.error : catalogue.success ? '' : catalogue.error}
        />
        <Button variant="outline" asChild>
          <Link href="/strategies">Back to strategies</Link>
        </Button>
      </div>
    );
  }

  const taken = new Set(strategies.map((strategy) => strategy.slug));
  const initial = source
    ? duplicateValues(source, catalogue.data, taken)
    : emptyFormValues(catalogue.data);

  return (
    <div className="space-y-6">
      {heading}
      <Card>
        <CardHeader>
          <CardTitle>Definition</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {staleSource && <ErrorBanner message={STRATEGY_NOT_FOUND_MESSAGE} />}
          <StrategyForm mode="create" catalogue={catalogue.data} initial={initial} />
        </CardContent>
      </Card>
    </div>
  );
}
