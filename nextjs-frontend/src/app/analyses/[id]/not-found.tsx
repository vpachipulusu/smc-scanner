import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { ANALYSIS_NOT_FOUND_MESSAGE } from '@/lib/api/analyses-messages';

/** Shown for a malformed or unknown analysis id. */
export default function AnalysisNotFound() {
  return (
    <div className="space-y-4">
      <h1 className="text-3xl font-bold tracking-tight">Analysis not found</h1>
      <p className="text-muted-foreground">{ANALYSIS_NOT_FOUND_MESSAGE}</p>
      <Button variant="outline" asChild>
        <Link href="/">Back to dashboard</Link>
      </Button>
    </div>
  );
}
