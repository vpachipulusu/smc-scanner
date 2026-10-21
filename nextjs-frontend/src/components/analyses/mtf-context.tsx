import { knownTimeframes, higherTimeframe, NOT_APPLICABLE } from '@/lib/scan/mtf';
import type { AnalysisOut } from '@/lib/api/analyses';

/**
 * Which timeframes fed a stored analysis and whether it had a higher one. Informational only:
 * higher-timeframe context is not part of the 0-4 score. Names are checked against the known
 * timeframes, so stored text never reaches the page.
 */
export function MtfContext({ analysis }: { analysis: AnalysisOut }) {
  const used = knownTimeframes(analysis.timeframes_used);
  const higher = higherTimeframe(analysis.tf, used);
  return (
    <section
      aria-labelledby="mtf-context-heading"
      className="rounded-lg border p-4 text-sm"
      data-testid="mtf-context"
    >
      <h2 id="mtf-context-heading" className="sr-only">
        Timeframes
      </h2>
      <dl className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-0.5">
          <dt className="text-sm text-muted-foreground">Timeframes used</dt>
          <dd className="font-medium">{used.length > 0 ? used.join(', ') : NOT_APPLICABLE}</dd>
        </div>
        <div className="space-y-0.5">
          <dt className="text-sm text-muted-foreground">Higher timeframe</dt>
          <dd className="font-medium">{higher ?? NOT_APPLICABLE}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-muted-foreground">
        Higher-timeframe context is advisory and not part of the 0-4 score.
      </p>
    </section>
  );
}
