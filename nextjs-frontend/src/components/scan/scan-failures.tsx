import { TriangleAlert } from 'lucide-react';
import type { ScanFailureOut } from '@/lib/api/scan';

/** Symbols the API skipped (unknown name, no candles, too few bars); the rest of the scan still ran. */
export function ScanFailures({ failures }: { failures: ReadonlyArray<ScanFailureOut> }) {
  if (failures.length === 0) return null;
  return (
    <section
      aria-labelledby="scan-failures-heading"
      data-testid="scan-failures"
      className="rounded-lg border border-warn-foreground/30 bg-warn p-4 text-sm text-warn-foreground"
    >
      <h2 id="scan-failures-heading" className="flex items-center gap-2 font-semibold">
        <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />
        {failures.length === 1 ? '1 symbol skipped' : `${failures.length} symbols skipped`}
      </h2>
      <ul className="mt-2 space-y-1">
        {failures.map((failure) => (
          <li key={failure.symbol} className="flex flex-wrap gap-x-2">
            <span className="font-mono">{failure.symbol}</span>
            <span>{failure.error}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
