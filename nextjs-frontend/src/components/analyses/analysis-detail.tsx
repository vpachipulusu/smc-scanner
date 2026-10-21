import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

import { ActionPill } from '@/components/common/action-pill';
import { ConfidenceBar } from '@/components/common/confidence-bar';
import { CalendarSlot } from '@/components/calendar/calendar-card';
import { LogTradeButton } from '@/components/journal/log-trade-button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { AiVerdict, AnalysisOut } from '@/lib/api/analyses';
import type { CalendarResult } from '@/lib/api/calendar';
import { NOT_AVAILABLE, formatPrice, formatUtc, stringList, textOrNA } from './format';
import { MtfContext } from './mtf-context';
import { SetupChart } from './setup-chart';
import { TradeSetupCard } from './trade-setup-card';

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  );
}

function providerModel(analysis: AnalysisOut): string {
  const parts = [analysis.provider, analysis.model].filter((part) => part && part.trim());
  return parts.length === 0 ? NOT_AVAILABLE : parts.join(' / ');
}

function zoneRange(analysis: AnalysisOut): string {
  return `${formatPrice(analysis.zone_low)} to ${formatPrice(analysis.zone_high)}`;
}

function Notice({ children }: { children: string }) {
  return (
    <p role="status" className="rounded-lg border p-4 text-sm text-muted-foreground">
      {children}
    </p>
  );
}

function Reasons({ verdict }: { verdict: AiVerdict }) {
  const reasons = stringList(verdict.reasons);
  const summary = typeof verdict.summary === 'string' ? verdict.summary.trim() : '';
  return (
    <Card>
      <CardHeader>
        <CardTitle>Reasons</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {summary && <p className="text-sm">{summary}</p>}
        {reasons.length === 0 ? (
          <p className="text-sm text-muted-foreground">No reasons recorded.</p>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** One stored analysis in full. All text is rendered as text, never as markup. */
export function AnalysisDetail({
  analysis,
  calendar,
}: {
  analysis: AnalysisOut;
  calendar?: CalendarResult;
}) {
  const { verdict } = analysis;
  return (
    <div className="space-y-6">
      <Link
        href="/"
        className="inline-flex min-h-10 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Back to dashboard
      </Link>

      <header className="space-y-3">
        <h1 className="text-3xl font-bold tracking-tight">
          {analysis.symbol} <span className="text-muted-foreground">{analysis.tf}</span>
        </h1>
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="Bar time" value={formatUtc(analysis.bar_time)} />
          <Fact label="Analysed" value={formatUtc(analysis.created_at)} />
          <Fact label="Provider / model" value={providerModel(analysis)} />
          <Fact label="Prompt version" value={textOrNA(analysis.prompt_version)} />
        </dl>
        {verdict && (
          <div className="flex flex-wrap items-center gap-3">
            <ActionPill action={verdict.action} />
            <ConfidenceBar value={verdict.confidence} />
          </div>
        )}
        <LogTradeButton analysis={analysis} />
      </header>

      <p className="rounded-lg border p-3 text-sm text-muted-foreground">
        This verdict is advisory only, no orders are placed.
      </p>

      <MtfContext analysis={analysis} />

      {calendar && <CalendarSlot result={calendar} />}

      {verdict ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <TradeSetupCard verdict={verdict} />
          <SetupChart analysis={analysis} verdict={verdict} />
          <Reasons verdict={verdict} />
        </div>
      ) : (
        <Notice>
          {analysis.status === 'failed'
            ? 'This analysis failed, so there is no verdict.'
            : 'This analysis stored no verdict.'}
        </Notice>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Scanner context</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Fact label="Zone" value={textOrNA(analysis.zone)} />
            <Fact label="Zone kind" value={textOrNA(analysis.zone_kind)} />
            <Fact label="Zone range" value={zoneRange(analysis)} />
            <Fact label="Attempts" value={String(analysis.attempts ?? NOT_AVAILABLE)} />
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}
