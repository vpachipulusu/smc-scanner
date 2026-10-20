import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

/** Shown while the server reads the first page of analyses. */
export default function HistoryLoading() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading analyses">
      <div className="space-y-2">
        <Skeleton className="h-9 w-40" />
        <Skeleton className="h-5 w-64 max-w-full" />
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
