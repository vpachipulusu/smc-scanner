import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

/** Shown while the server runs the scan (seconds on MT5: one symbol at a time). */
export default function ScanLoading() {
  return (
    <div className="space-y-6" role="status" aria-label="Scanning">
      <div className="space-y-2">
        <Skeleton className="h-9 w-32" />
        <Skeleton className="h-5 w-96 max-w-full" />
      </div>
      <Card>
        <CardContent className="space-y-4 pt-6">
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-11 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}
