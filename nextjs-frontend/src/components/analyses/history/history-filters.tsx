import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { historyHref, type HistoryParams } from './params';

/**
 * A GET form, like the scan form: submitting navigates to `/analyses?...` (without a cursor, so a
 * new filter starts at the newest page) and the server queries the API. Works without JavaScript
 * and every view has a shareable URL.
 */

const SELECT_CLASSES =
  'h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';

const ACTION_CHOICES = ['BUY', 'SELL', 'HOLD'] as const;

export function HistoryFilters({ params }: { params: HistoryParams }) {
  const filtered = historyHref(params, '/analyses', false) !== '/analyses';

  return (
    <form
      action="/analyses"
      method="get"
      role="search"
      aria-label="Filter analyses"
      className="space-y-4"
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <Label htmlFor="history-symbol" className="mb-1 block">
            Symbol
          </Label>
          <Input
            id="history-symbol"
            name="symbol"
            defaultValue={params.symbol ?? ''}
            maxLength={32}
            placeholder="All symbols"
            autoComplete="off"
            className="h-11"
          />
        </div>
        <div>
          <Label htmlFor="history-action" className="mb-1 block">
            Action
          </Label>
          <select
            id="history-action"
            name="action"
            defaultValue={params.action ?? ''}
            className={SELECT_CLASSES}
          >
            <option value="">Any</option>
            {ACTION_CHOICES.map((action) => (
              <option key={action} value={action}>
                {action}
              </option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor="history-min-conf" className="mb-1 block">
            Min confidence
          </Label>
          <Input
            id="history-min-conf"
            name="min_conf"
            type="number"
            inputMode="decimal"
            min={0}
            max={100}
            step="any"
            defaultValue={params.minConfidence ?? ''}
            placeholder="0–100 %"
            className="h-11"
          />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit">Apply filters</Button>
        {filtered && (
          <Button variant="outline" asChild>
            <Link href="/analyses">Reset</Link>
          </Button>
        )}
      </div>
    </form>
  );
}
