import { Skeleton } from '@/components/ui/skeleton';

export default function StrategiesLoading() {
  return (
    <div className="space-y-6" aria-busy="true">
      <span className="sr-only" role="status">
        Loading strategies…
      </span>
      <Skeleton className="h-9 w-48" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-56 w-full" />
        <Skeleton className="h-56 w-full" />
      </div>
    </div>
  );
}
