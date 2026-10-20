import { Skeleton } from '@/components/ui/skeleton';

export default function AutomationLoading() {
  return (
    <div className="space-y-6" aria-busy="true">
      <Skeleton className="h-9 w-48" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}
