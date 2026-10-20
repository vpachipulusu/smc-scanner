import Link from 'next/link';
import { ArrowLeft, TriangleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';

/**
 * Error for the detail page: the heading and back link the loaded page has, one of the fixed
 * messages (`fetchAnalysis` never passes raw API text) and a Retry link. Retry is a Link to the
 * same route: the page is `force-dynamic`, so navigating to it renders it again and refetches.
 */
export function AnalysisLoadError({ message, id }: { message: string; id: number }) {
  return (
    <div className="space-y-6">
      <Link
        href="/"
        className="inline-flex min-h-10 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Back to dashboard
      </Link>
      <h1 className="text-3xl font-bold tracking-tight">Analysis #{id}</h1>
      <div
        role="alert"
        className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/50 p-4 text-sm text-crit-foreground"
      >
        <p className="flex items-center gap-2">
          <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />
          {message}
        </p>
        <Button variant="outline" asChild>
          <Link href={`/analyses/${id}`}>Retry</Link>
        </Button>
      </div>
    </div>
  );
}
