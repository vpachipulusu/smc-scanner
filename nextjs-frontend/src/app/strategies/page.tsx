import Link from 'next/link';

import { ErrorBanner } from '@/components/dashboard/error-banner';
import { PageNotice } from '@/components/strategies/page-notice';
import { StrategyList } from '@/components/strategies/strategy-list';
import { Button } from '@/components/ui/button';
import { fetchConditionCatalogue, fetchStrategies } from '@/lib/api/strategies-write';
import { SLUG_PATTERN } from '@/lib/strategies/schema';

/** Strategies change from this page and the CLI, so the list is always read live. */
export const dynamic = 'force-dynamic';

export const metadata = { title: 'Strategies' };

type SearchParams = Promise<{ saved?: string | string[]; deleted?: string | string[] }>;

const slugParam = (raw: string | string[] | undefined): string | null =>
  typeof raw === 'string' && SLUG_PATTERN.test(raw) ? raw : null;

export default async function StrategiesPage({ searchParams }: { searchParams: SearchParams }) {
  const { saved, deleted } = await searchParams;
  const [result, catalogue] = await Promise.all([fetchStrategies(), fetchConditionCatalogue()]);
  const strategies = result.success ? result.data : [];
  // Labels only: without the catalogue, conditions show their keys.
  const conditions = catalogue.success ? catalogue.data : [];
  const savedSlug = slugParam(saved);
  const savedStrategy = strategies.find((strategy) => strategy.slug === savedSlug);
  const deletedSlug = slugParam(deleted);
  const deletedGone =
    result.success &&
    deletedSlug !== null &&
    !strategies.some((strategy) => strategy.slug === deletedSlug);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Strategies</h1>
          <p className="text-muted-foreground">
            What a scan looks for: zone kinds, required conditions and scored conditions.
          </p>
        </div>
        {result.success && (
          <Button asChild>
            <Link href="/strategies/new">New strategy</Link>
          </Button>
        )}
      </div>

      {savedStrategy && <PageNotice>Saved “{savedStrategy.name}”.</PageNotice>}
      {deletedGone && <PageNotice>Deleted strategy {deletedSlug}.</PageNotice>}

      {!result.success ? (
        <div className="space-y-3">
          <ErrorBanner message={result.error} />
          <Button variant="outline" asChild>
            <Link href="/strategies">Retry</Link>
          </Button>
        </div>
      ) : (
        <StrategyList strategies={strategies} catalogue={conditions} />
      )}
    </div>
  );
}
