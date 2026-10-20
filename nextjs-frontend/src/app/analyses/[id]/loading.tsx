import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

/** Shown while the server loads one analysis. */
export default function AnalysisLoading() {
  return (
    <div className="space-y-6" role="status" aria-busy="true" aria-label="Loading analysis">
      <div className="space-y-2">
        <Skeleton className="h-9 w-48" />
        <Skeleton className="h-5 w-72 max-w-full" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {[0, 1].map((i) => (
          <Card key={i}>
            <CardContent className="space-y-3 pt-6">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-24 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
