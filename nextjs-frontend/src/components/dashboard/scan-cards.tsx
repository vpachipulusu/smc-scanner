import { DashboardCard } from './dashboard-card';
import { ScanFailures } from '@/components/scan/scan-failures';
import { StatusPill } from '@/components/ui/status-pill';
import type { ScanResponse } from '@/lib/api/scan';

export function TouchingCard({ rows }: { rows: ScanResponse['rows'] }) {
  const touching = rows.filter((row) => row.status === 'TOUCHING');
  return (
    <DashboardCard title="TOUCHING now">
      {touching.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No instrument is touching a fresh zone right now.
        </p>
      ) : (
        <ul className="divide-y">
          {touching.map((row) => (
            <li
              key={`${row.instrument}-${row.zone}-${row.bar_time}`}
              className="flex flex-wrap items-center gap-3 py-2"
            >
              <span className="min-w-20 font-medium">{row.instrument}</span>
              <StatusPill variant="good">TOUCHING</StatusPill>
              <span className="text-sm text-muted-foreground">{row.zone}</span>
            </li>
          ))}
        </ul>
      )}
    </DashboardCard>
  );
}

export function SummaryCard({ response }: { response: ScanResponse }) {
  const total = response.rows.length;
  const near = response.rows.filter((row) => row.status === 'NEAR').length;
  const touching = response.rows.filter((row) => row.status === 'TOUCHING').length;
  return (
    <DashboardCard title="Latest scan summary">
      <div className="space-y-3">
        <p className="text-sm">
          {total} {total === 1 ? 'row' : 'rows'} on {response.tf} ({response.source}): {touching}{' '}
          touching, {near} near.
        </p>
        <ScanFailures failures={response.failures} />
      </div>
    </DashboardCard>
  );
}
