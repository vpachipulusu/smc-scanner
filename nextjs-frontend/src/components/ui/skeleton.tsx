import * as React from 'react';

import { cn } from '@/lib/utils';

/**
 * Loading placeholder. Size comes from the caller (className) and never changes;
 * the pulse only runs when the user has not asked for reduced motion.
 * Decorative (aria-hidden): mark the loading container `aria-busy`. Use on card or
 * background surfaces; it blends into `--secondary` surfaces.
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn('rounded-md bg-secondary motion-safe:animate-pulse', className)}
      {...props}
    />
  );
}

export { Skeleton };
