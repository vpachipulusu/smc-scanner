import { CircleSlash, FlaskConical, ShieldCheck, ShieldX, TriangleAlert } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { StatusPill } from '@/components/ui/status-pill';
import {
  VERDICT_DESCRIPTIONS,
  VERDICT_LABELS,
  VERDICT_VARIANTS,
  type VerdictKey,
} from '@/lib/backtests/verdict';

/**
 * A strategy's backtest verdict: icon, text and tint, never colour alone. The visible text is the
 * verdict; screen readers also hear that it is a backtest verdict, unless the surrounding text
 * already says so (`labelled={false}`).
 */

const ICONS: Readonly<Record<VerdictKey, LucideIcon>> = {
  survived: ShieldCheck,
  failed: ShieldX,
  insufficient: TriangleAlert,
  'not-run': FlaskConical,
  unknown: CircleSlash,
};

type VerdictBadgeProps = { verdict: VerdictKey; className?: string; labelled?: boolean };

export function VerdictBadge({ verdict, className, labelled = true }: VerdictBadgeProps) {
  return (
    <StatusPill
      variant={VERDICT_VARIANTS[verdict]}
      icon={ICONS[verdict]}
      title={VERDICT_DESCRIPTIONS[verdict]}
      className={className}
      data-verdict={verdict}
    >
      {labelled && <span className="sr-only">Backtest verdict: </span>}
      {VERDICT_LABELS[verdict]}
    </StatusPill>
  );
}
