import { ArrowDown, ArrowUp, Minus, type LucideIcon } from 'lucide-react';

import { StatusPill, type StatusPillVariant } from '@/components/ui/status-pill';

/** The verdict action, defined locally so this stays presentational and independent of the API client. */
export type ActionPillAction = 'BUY' | 'SELL' | 'HOLD';

const ACTION_STYLES: Record<ActionPillAction, { variant: StatusPillVariant; icon: LucideIcon }> = {
  BUY: { variant: 'good', icon: ArrowUp },
  SELL: { variant: 'crit', icon: ArrowDown },
  HOLD: { variant: 'neutral', icon: Minus },
};

/** BUY / SELL / HOLD as icon + text + tint, never colour alone. */
export function ActionPill({ action }: { action: ActionPillAction }) {
  const style = ACTION_STYLES[action] ?? ACTION_STYLES.HOLD;
  return (
    <StatusPill variant={style.variant} icon={style.icon}>
      {action}
    </StatusPill>
  );
}
