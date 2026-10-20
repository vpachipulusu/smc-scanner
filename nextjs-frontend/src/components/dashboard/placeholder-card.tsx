import { DashboardCard } from './dashboard-card';

/** A card for data that has no source yet. Says so in words instead of showing fake numbers. */
export function PlaceholderCard({ title }: { title: string }) {
  return (
    <DashboardCard title={title}>
      <p className="text-sm text-muted-foreground">
        Not available yet: available after the Analyses API / scheduler land.
      </p>
    </DashboardCard>
  );
}
