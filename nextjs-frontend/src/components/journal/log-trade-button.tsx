import Link from 'next/link';

import { Button } from '@/components/ui/button';
import type { AnalysisOut } from '@/lib/api/analyses';
import { buildLogTradeHref } from '@/lib/journal/prefill';

/** Opens the journal's new-entry form prefilled from this analysis (symbol, side, entry, stop). */
export function LogTradeButton({ analysis }: { analysis: AnalysisOut }) {
  return (
    <Button variant="outline" asChild>
      <Link href={buildLogTradeHref(analysis)}>Log trade</Link>
    </Button>
  );
}
