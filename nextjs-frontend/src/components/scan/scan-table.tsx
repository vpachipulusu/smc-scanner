import { Check, Minus } from 'lucide-react';
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

export function ScanTable({ rows }: { rows: ReadonlyArray<ScanRowOut> }) {
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
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
