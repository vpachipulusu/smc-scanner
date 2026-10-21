'use client';

import { ErrorBanner } from '@/components/dashboard/error-banner';
import { Button } from '@/components/ui/button';

/**
 * Error boundary for the journal routes. The thrown error is never shown or logged here: its text
 * could carry backend detail, so only a fixed message is displayed.
 */
export default function JournalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="space-y-3">
      <ErrorBanner message="Something went wrong while showing the journal." />
      <Button variant="outline" onClick={reset}>
        Try again
      </Button>
    </div>
  );
}
