import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { AiVerdict } from '@/lib/api/analyses';
import { NOT_AVAILABLE, formatPrice, isFiniteNumber, numberList, textOrNA } from './format';

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function riskReward(value: number | null | undefined): string {
  return isFiniteNumber(value) ? `1 : ${Number(value.toFixed(2))}` : NOT_AVAILABLE;
}

/** Quality, entry, stop, targets and risk:reward of one verdict. */
export function TradeSetupCard({ verdict }: { verdict: AiVerdict }) {
  const targets = numberList(verdict.targets);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Trade setup</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="divide-y">
          <Row label="Quality" value={textOrNA(verdict.quality)} />
          <Row label="Entry" value={formatPrice(verdict.entry)} />
          <Row label="Stop" value={formatPrice(verdict.stop)} />
          {targets.length === 0 ? (
            <Row label="Targets" value={NOT_AVAILABLE} />
          ) : (
            targets.map((target, index) => (
              <Row key={index} label={`Target ${index + 1}`} value={formatPrice(target)} />
            ))
          )}
          <Row label="Risk : reward" value={riskReward(verdict.risk_reward)} />
          <Row label="Invalidation" value={formatPrice(verdict.invalidation)} />
        </dl>
        {verdict.downgraded && (
          <p className="mt-3 text-sm text-muted-foreground">
            Downgraded: {verdict.downgrade_reason?.trim() || NOT_AVAILABLE}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
