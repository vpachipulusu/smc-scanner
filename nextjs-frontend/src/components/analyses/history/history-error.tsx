import Link from 'next/link';
import { TriangleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';

/**
 * Error for the history list. The message is one of the fixed ones from `analyses-messages.ts`
 * (`fetchAnalyses` never passes raw API text). Retry is a Link to the same filtered URL: the page
 * is `force-dynamic`, so navigating to it renders it again.
 */
export function HistoryError({ message, retryHref }: { message: string; retryHref: string }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/50 p-4 text-sm text-crit-foreground"
    >
      <p className="flex items-center gap-2">
        <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />
        {message}
      </p>
      <Button variant="outline" asChild>
        <Link href={retryHref}>Retry</Link>
      </Button>
    </div>
  );
}
