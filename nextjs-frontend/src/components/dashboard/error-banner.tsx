import { TriangleAlert } from 'lucide-react';

import { cn } from '@/lib/utils';

/** An alert for a card whose data could not be loaded. The message is already safe to show. */
export function ErrorBanner({ message, className }: { message: string; className?: string }) {
  return (
    <div
      role="alert"
      className={cn(
        'flex items-center gap-2 rounded-lg border border-destructive/50 p-4 text-sm text-crit-foreground',
        className
      )}
    >
      <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />
      {message}
    </div>
  );
}
