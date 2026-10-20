import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { Box, Check, Clock, TriangleAlert, Undo2, type LucideIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

const statusPillVariants = cva(
  'inline-flex min-h-6 items-center gap-1 rounded-full py-0.5 pl-2 pr-2.5 text-[0.8125rem] font-semibold leading-none whitespace-nowrap',
  {
    variants: {
      variant: {
        good: 'bg-good text-good-foreground',
        warn: 'bg-warn text-warn-foreground',
        crit: 'bg-crit text-crit-foreground',
        info: 'bg-info text-info-foreground',
        neutral: 'bg-secondary text-foreground',
      },
    },
    defaultVariants: {
      variant: 'neutral',
    },
  }
);

export type StatusPillVariant = NonNullable<VariantProps<typeof statusPillVariants>['variant']>;

const STATUS_ICONS: Record<StatusPillVariant, LucideIcon> = {
  good: Check,
  warn: Clock,
  crit: TriangleAlert,
  info: Box,
  neutral: Undo2,
};

export interface StatusPillProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof statusPillVariants> {
  /** Overrides the variant's default icon, e.g. Pencil for a Draft pill. */
  icon?: LucideIcon;
}

/** Status is always icon + text + tint, never colour alone. The icon is decorative. Inline-safe (a span). */
function StatusPill({ className, variant, icon, children, ...props }: StatusPillProps) {
  const Icon = icon ?? STATUS_ICONS[variant ?? 'neutral'];

  return (
    <span className={cn(statusPillVariants({ variant }), className)} {...props}>
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      {children}
    </span>
  );
}

export { StatusPill, statusPillVariants };
