import { Check, Minus } from 'lucide-react';
import { ActionPill } from '@/components/common/action-pill';
import { ConfidenceBar } from '@/components/common/confidence-bar';
import { StatusPill, type StatusPillVariant } from '@/components/ui/status-pill';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { AiResultOut } from '@/lib/api/analyse';
import type { ScanRowOut } from '@/lib/api/scan';
import { cn } from '@/lib/utils';

/** Rows arrive sorted by the API (TOUCHING first, then score, then distance); this only renders them. */

const STATUS_VARIANT: Record<ScanRowOut['status'], StatusPillVariant> = {
  TOUCHING: 'good',
  NEAR: 'info',
};

const BIAS_VARIANT: Record<ScanRowOut['bias'], StatusPillVariant> = {
  bullish: 'good',
  bearish: 'crit',
  range: 'neutral',
};

export const MAX_SCORE = 4;

/** Full quote precision without float noise (1.08235 stays 1.08235; 65432.1 stays 65432.1). */
export function formatPrice(value: number): string {
  return value.toFixed(10).replace(/0+$/, '').replace(/\.$/, '');
}

function YesNo({ value, label }: { value: boolean; label: string }) {
  const Icon = value ? Check : Minus;
  return (
    <span
      className={cn(
        'inline-flex items-center',
        value ? 'text-good-foreground' : 'text-muted-foreground'
      )}
    >
      <Icon aria-hidden="true" className="size-4" />
      <span className="sr-only">{`${label}: ${value ? 'yes' : 'no'}`}</span>
    </span>
  );
}

function ScorePips({ score }: { score: number }) {
  return (
    <span
      className="inline-flex items-center gap-1"
      role="img"
      aria-label={`Score ${score} of ${MAX_SCORE}`}
    >
      {Array.from({ length: MAX_SCORE }, (_, index) => (
        <span
          key={index}
          aria-hidden="true"
          data-filled={index < score}
          className={cn(
            'inline-block size-2 rounded-full',
            index < score ? 'bg-primary' : 'bg-border'
          )}
        />
      ))}
      <span aria-hidden="true" className="ml-1 tabular-nums">
        {score}
      </span>
    </span>
  );
}

/** A scan row, optionally with the AI result the analysis added. */
export type ScanTableRow = ScanRowOut & { ai?: AiResultOut };

function Setup({ verdict }: { verdict: NonNullable<AiResultOut['verdict']> }) {
  const parts: string[] = [];
  if (verdict.quality) parts.push(`Grade ${verdict.quality}`);
  if (typeof verdict.entry === 'number') parts.push(`Entry ${formatPrice(verdict.entry)}`);
  if (typeof verdict.stop === 'number') parts.push(`Stop ${formatPrice(verdict.stop)}`);
  if (verdict.targets && verdict.targets.length > 0) {
    parts.push(`TP ${verdict.targets.map(formatPrice).join(', ')}`);
  }
  if (typeof verdict.risk_reward === 'number') parts.push(`R:R ${verdict.risk_reward.toFixed(2)}`);
  if (parts.length === 0) return <NoValue />;
  return (
    <ul className="space-y-0.5 text-xs tabular-nums">
      {parts.map((part) => (
        <li key={part}>{part}</li>
      ))}
    </ul>
  );
}

/** An empty cell that is still announced, so a row without a verdict reads as "none", not broken. */
function NoValue() {
  return (
    <span className="text-muted-foreground">
      <span aria-hidden="true">—</span>
      <span className="sr-only">No verdict</span>
    </span>
  );
}

function AiCells({ ai }: { ai: AiResultOut | undefined }) {
  const verdict = ai?.verdict ?? null;
  return (
    <>
      <TableCell label="Action">
        {verdict ? <ActionPill action={verdict.action} /> : <NoValue />}
      </TableCell>
      <TableCell label="Confidence">
        {verdict ? <ConfidenceBar value={verdict.confidence} /> : <NoValue />}
      </TableCell>
      <TableCell label="Setup">{verdict ? <Setup verdict={verdict} /> : <NoValue />}</TableCell>
    </>
  );
}

export function ScanTable({
  rows,
  showAi = false,
}: {
  rows: ReadonlyArray<ScanTableRow>;
  showAi?: boolean;
}) {
  return (
    <Table stacked>
      <TableCaption>Instruments touching or near a fresh zone, best first</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>Instrument</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Zone</TableHead>
          <TableHead numeric>Low</TableHead>
          <TableHead numeric>High</TableHead>
          <TableHead numeric>Price</TableHead>
          <TableHead numeric>Dist (ATR)</TableHead>
          <TableHead>Bias</TableHead>
          <TableHead>OTE</TableHead>
          <TableHead>Trend</TableHead>
          <TableHead>OB+FVG</TableHead>
          <TableHead>Score</TableHead>
          <TableHead numeric>Age</TableHead>
          <TableHead numeric>Touches</TableHead>
          <TableHead>Bar</TableHead>
          {showAi && (
            <>
              <TableHead>Action</TableHead>
              <TableHead>Confidence</TableHead>
              <TableHead>Setup</TableHead>
            </>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow
            key={`${row.instrument}-${row.zone}-${row.zone_low}-${index}`}
            data-testid="scan-row"
          >
            <TableCell className="font-medium" label="Instrument">
              {row.instrument}
            </TableCell>
            <TableCell label="Status">
              <StatusPill variant={STATUS_VARIANT[row.status]}>{row.status}</StatusPill>
            </TableCell>
            <TableCell label="Zone">{row.zone}</TableCell>
            <TableCell numeric label="Low">
              {formatPrice(row.zone_low)}
            </TableCell>
            <TableCell numeric label="High">
              {formatPrice(row.zone_high)}
            </TableCell>
            <TableCell numeric label="Price">
              {formatPrice(row.price)}
            </TableCell>
            <TableCell numeric label="Dist (ATR)">
              {row.dist_atr.toFixed(2)}
            </TableCell>
            <TableCell label="Bias">
              <StatusPill
                variant={BIAS_VARIANT[row.bias]}
                icon={row.bias === 'range' ? Minus : undefined}
              >
                {row.bias}
              </StatusPill>
            </TableCell>
            <TableCell label="OTE">
              <YesNo value={row.in_ote} label="In OTE" />
            </TableCell>
            <TableCell label="Trend">
              <YesNo value={row.trendline_ok} label="Trendline holds" />
            </TableCell>
            <TableCell label="OB+FVG">
              <YesNo value={row.ob_fvg} label="OB and FVG stacked" />
            </TableCell>
            <TableCell label="Score">
              <ScorePips score={row.score} />
            </TableCell>
            <TableCell numeric label="Age">
              {row.zone_age}
            </TableCell>
            <TableCell numeric label="Touches">
              {row.prior_touches}
            </TableCell>
            <TableCell label="Bar" className="font-mono text-xs">
              {row.bar_time}
            </TableCell>
            {showAi && <AiCells ai={row.ai} />}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
