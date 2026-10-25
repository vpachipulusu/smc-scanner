import Link from 'next/link';

import { ScheduleForm } from '@/components/automation/schedule-form';
import { SchedulesTable } from '@/components/automation/schedules-table';
import { ErrorBanner } from '@/components/dashboard/error-banner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { fetchBacktestVerdicts } from '@/lib/api/backtests';
import { fetchScanConfig } from '@/lib/api/scan';
import { fetchSchedules } from '@/lib/api/schedules';
import { fetchStrategies } from '@/lib/api/strategies';
import { SCHEDULE_NOT_FOUND_MESSAGE } from '@/lib/api/schedules-messages';
import { parseScheduleId } from '@/lib/automation/form';
import { strategyOptions } from '@/lib/scan/strategy-options';

/** Schedules change from the scheduler as well as from this page, so it is always read live. */
export const dynamic = 'force-dynamic';

/** Run now waits for the scan and the AI; server actions inherit this limit. */
export const maxDuration = 60;

export const metadata = { title: 'Automation' };

type SearchParams = Promise<{ edit?: string | string[] }>;

export default async function AutomationPage({ searchParams }: { searchParams: SearchParams }) {
  const { edit } = await searchParams;
  const configPromise = fetchScanConfig();
  const strategiesPromise = fetchStrategies();
  // The picker's verdict badges need only the strategy list, so they load beside the schedules.
  const optionsPromise = Promise.all([configPromise, strategiesPromise]).then(([c, s]) =>
    strategyOptions(c.success ? c.data : null, s.success ? s.data : null)
  );
  const [result, strategiesResult, options, verdicts] = await Promise.all([
    fetchSchedules(),
    strategiesPromise,
    optionsPromise,
    optionsPromise.then((list) => fetchBacktestVerdicts(list.map((option) => option.slug))),
  ]);
  const strategies = strategiesResult.success ? strategiesResult.data : null;
  // Only the full list is authoritative: /config falls back to the built-ins when the store is down.
  const knownStrategies = strategies ? new Set(strategies.map((item) => item.slug)) : null;
  const editId = parseScheduleId(edit);
  const schedules = result.success ? result.data : [];
  const editing = editId === null ? undefined : schedules.find((s) => s.id === editId);
  const staleEdit = result.success && edit !== undefined && editing === undefined;

  return (
    <div className="space-y-6">
      <div>
        <h1
          id="automation-heading"
          tabIndex={-1}
          className="text-3xl font-bold tracking-tight outline-none"
        >
          Automation
        </h1>
        <p className="text-muted-foreground">
          Scheduled scans that analyse hits and send them to Telegram.
        </p>
      </div>

      {!result.success ? (
        <div className="space-y-3">
          <ErrorBanner message={result.error} />
          <Button variant="outline" asChild>
            <Link href="/automation">Retry</Link>
          </Button>
        </div>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Schedules</CardTitle>
          </CardHeader>
          <CardContent>
            {schedules.length === 0 ? (
              <p className="text-sm text-muted-foreground" data-testid="no-schedules">
                No schedules yet. Create one below.
              </p>
            ) : (
              <SchedulesTable schedules={schedules} knownStrategies={knownStrategies} />
            )}
          </CardContent>
        </Card>
      )}

      {result.success && (
        <Card>
          <CardHeader>
            <CardTitle>{editing ? `Edit “${editing.name}”` : 'New schedule'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {staleEdit && <ErrorBanner message={SCHEDULE_NOT_FOUND_MESSAGE} />}
            <ScheduleForm
              key={editing ? `${editing.id}-${editing.enabled}` : 'new'}
              schedule={editing}
              strategies={options}
              strategiesComplete={strategies !== null}
              strategyVerdicts={verdicts}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
