'use client';

import { useActionState } from 'react';
import { Loader2, Sparkles, TriangleAlert } from 'lucide-react';
import { analyseScanAction } from '@/app/scan/actions';
import { ScanFailures } from '@/components/scan/scan-failures';
import { ScanTable, type ScanTableRow } from '@/components/scan/scan-table';
import { Button } from '@/components/ui/button';
import { ANALYSE_DISABLED_HINT, NO_VERDICT_REASON, skipReason } from '@/lib/api/analyse-messages';
import type { AnalysedRowOut } from '@/lib/api/analyse';
import type { ScanFailureOut } from '@/lib/api/scan';
import { IDLE_ANALYSE_STATE, type AnalyseState } from '@/lib/scan/analyse-state';
import { scanSearchParams, type ScanPageParams } from '@/lib/scan/params';

/**
 * The scan results plus the "Analyse with AI" form. The form is a server action carrying the scan
 * options in hidden fields; while it runs the button shows a pending state and the rest of the page
 * stays usable. After it returns, the table gains Action / Confidence / Setup columns. Only fixed
 * messages reach the screen: the action never returns backend text.
 */

function withoutVerdict(rows: ReadonlyArray<AnalysedRowOut>): AnalysedRowOut[] {
  return rows.filter((row) => row.ai.verdict === null);
}

function AiSkipped({ rows }: { rows: ReadonlyArray<AnalysedRowOut> }) {
  if (rows.length === 0) return null;
  return (
    <section
      aria-labelledby="ai-skipped-heading"
      data-testid="ai-skipped"
      className="rounded-lg border border-warn-foreground/30 bg-warn p-4 text-sm text-warn-foreground"
    >
      <h2 id="ai-skipped-heading" className="flex items-center gap-2 font-semibold">
        <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />
        {rows.length === 1
          ? '1 hit without an AI verdict'
          : `${rows.length} hits without an AI verdict`}
      </h2>
      <ul className="mt-2 space-y-1">
        {rows.map((row, index) => (
          <li key={`${row.instrument}-${row.zone}-${index}`} className="flex flex-wrap gap-x-2">
            <span className="font-mono">{row.instrument}</span>
            <span>{skipReason(row.ai.status) ?? NO_VERDICT_REASON}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AnalyseStatus({ pending, state }: { pending: boolean; state: AnalyseState }) {
  let text: string | null = null;
  if (pending) {
    text = 'Analysing the hits with AI. This can take a minute; you can keep using the page.';
  } else if (state.status === 'success') {
    const total = state.rows.length;
    const analysed = total - withoutVerdict(state.rows).length;
    text = `${analysed} of ${total} ${total === 1 ? 'hit' : 'hits'} analysed.`;
  }
  return (
    <div role="status" className="text-sm text-muted-foreground">
      {text}
    </div>
  );
}

export function ScanAnalysis({
  params,
  rows,
  failures,
  aiEnabled,
}: {
  params: ScanPageParams;
  rows: ReadonlyArray<ScanTableRow>;
  failures: ReadonlyArray<ScanFailureOut>;
  aiEnabled: boolean;
}) {
  const [state, formAction, pending] = useActionState(analyseScanAction, IDLE_ANALYSE_STATE);
  const analysed = state.status === 'success';
  const shownRows: ReadonlyArray<ScanTableRow> = analysed ? state.rows : rows;
  const shownFailures = analysed ? state.failures : failures;

  return (
    <div className="space-y-4">
      <form action={formAction} className="flex flex-wrap items-center gap-3">
        {[...scanSearchParams(params)].map(([name, value]) => (
          <input key={name} type="hidden" name={name} value={value} />
        ))}
        <Button
          type="submit"
          variant="accent"
          disabled={!aiEnabled || pending}
          aria-describedby={aiEnabled ? undefined : 'ai-disabled-hint'}
        >
          {pending ? (
            <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
          ) : (
            <Sparkles aria-hidden="true" />
          )}
          {pending ? 'Analysing…' : 'Analyse with AI'}
        </Button>
        {!aiEnabled && (
          <p id="ai-disabled-hint" className="text-sm text-muted-foreground">
            {ANALYSE_DISABLED_HINT}
          </p>
        )}
      </form>
      <AnalyseStatus pending={pending} state={state} />
      {state.status === 'error' && !pending && (
        <p
          role="alert"
          className="flex items-center gap-2 rounded-lg border border-destructive/50 p-4 text-sm text-destructive"
        >
          <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />
          {state.message}
        </p>
      )}
      {shownRows.length > 0 && <ScanTable rows={shownRows} showAi={analysed} />}
      {analysed && <AiSkipped rows={withoutVerdict(state.rows)} />}
      <ScanFailures failures={shownFailures} />
    </div>
  );
}
