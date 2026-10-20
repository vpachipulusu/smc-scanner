'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { RefreshCw } from 'lucide-react';

/**
 * The `--every N` behaviour: while `every` is in the URL, the page re-runs its server scan every
 * N minutes with `router.refresh()`, which keeps the form and the URL as they are. The time is
 * formatted in UTC with a fixed locale so the server and client render the same text.
 */

const MS_PER_MINUTE = 60_000;

const TIME_FORMAT = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  timeZone: 'UTC',
});

export function formatScanTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '—' : `${TIME_FORMAT.format(date)} UTC`;
}

export function AutoRefresh({
  everyMinutes,
  scannedAt,
  stopHref,
}: {
  everyMinutes: number;
  scannedAt: string;
  stopHref: string;
}) {
  const router = useRouter();

  useEffect(() => {
    if (everyMinutes <= 0) return undefined;
    const timer = setInterval(() => {
      // A hidden tab would scan MT5 for nobody; it catches up on the next tick after it is shown.
      if (document.visibilityState === 'visible') router.refresh();
    }, everyMinutes * MS_PER_MINUTE);
    return () => clearInterval(timer);
  }, [everyMinutes, router]);

  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
      <span data-testid="scanned-at">Last scan at {formatScanTime(scannedAt)}</span>
      {everyMinutes > 0 && (
        <>
          <span className="inline-flex items-center gap-1" data-testid="auto-refresh">
            <RefreshCw aria-hidden="true" className="size-3.5" />
            Rescanning every {everyMinutes} min
          </span>
          <Link href={stopHref} className="underline underline-offset-4">
            Stop
          </Link>
        </>
      )}
    </p>
  );
}
