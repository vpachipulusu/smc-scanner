import { DashboardCard } from './dashboard-card';

/** A card for data that has no source yet (needs the scheduler, TRAD-14). Says so in words instead of showing fake numbers. */
export function PlaceholderCard({ title }: { title: string }) {
  return (
    <DashboardCard title={title}>
      <p className="text-sm text-muted-foreground">Coming soon: needs the scheduler.</p>
    </DashboardCard>
  );
}
