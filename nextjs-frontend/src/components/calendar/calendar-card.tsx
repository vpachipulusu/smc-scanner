import { RiskBadge } from '@/components/calendar/risk-badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusPill } from '@/components/ui/status-pill';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { formatUtc } from '@/components/analyses/format';
import type { CalendarEventOut, CalendarResponse, CalendarResult } from '@/lib/api/calendar';
import {
  formatCurrency,
  formatFigure,
  formatTitle,
  impactLabel,
  impactTone,
  LOOKBACK_HOURS,
} from '@/lib/calendar/format';

const NOTE_CLASS = 'text-sm text-muted-foreground';

function EventRow({ event }: { event: CalendarEventOut }) {
  return (
    <TableRow>
      <TableCell className="whitespace-nowrap">{formatUtc(event.time)}</TableCell>
      <TableCell>{formatCurrency(event.currency)}</TableCell>
      <TableCell>
        <StatusPill variant={impactTone(event.impact)}>{impactLabel(event.impact)}</StatusPill>
      </TableCell>
      <TableCell className="max-w-[24rem] break-words">{formatTitle(event.title)}</TableCell>
      <TableCell className="text-right">{formatFigure(event.actual)}</TableCell>
      <TableCell className="text-right">{formatFigure(event.forecast)}</TableCell>
      <TableCell className="text-right">{formatFigure(event.previous)}</TableCell>
    </TableRow>
  );
}

function Body({ calendar }: { calendar: CalendarResponse }) {
  if (calendar.calendar_status === 'unavailable') {
    return (
      <p role="status" className={NOTE_CLASS}>
        The economic calendar is unavailable right now, so news risk is unknown. Check a calendar
        before trading.
      </p>
    );
  }
  if (calendar.currencies.length === 0) {
    return (
      <p className={NOTE_CLASS}>This symbol is not recognised, so no calendar currencies apply.</p>
    );
  }
  return (
    <>
      {calendar.calendar_status === 'stale' && (
        <p role="status" className={NOTE_CLASS}>
          The live feed failed. Showing cached data fetched {formatUtc(calendar.fetched_at)}.
        </p>
      )}
      {calendar.events.length === 0 ? (
        <p className={NOTE_CLASS}>
          No events in the window for {calendar.currencies.map(formatCurrency).join(', ')}.
        </p>
      ) : (
        <Table>
          <TableCaption className="sr-only">
            Economic events for {calendar.currencies.map(formatCurrency).join(', ')}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Currency</TableHead>
              <TableHead>Impact</TableHead>
              <TableHead>Event</TableHead>
              <TableHead className="text-right">Actual</TableHead>
              <TableHead className="text-right">Forecast</TableHead>
              <TableHead className="text-right">Previous</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {calendar.events.map((event, index) => (
              <EventRow key={`${index}|${event.time}|${event.title}`} event={event} />
            ))}
          </TableBody>
        </Table>
      )}
    </>
  );
}

/** Upcoming economic events for the symbol's currencies. Titles are third-party plain text. */
export function CalendarCard({ calendar }: { calendar: CalendarResponse }) {
  return (
    <Card>
      <CardHeader className="space-y-2">
        <CardTitle>Economic calendar</CardTitle>
        <p className={NOTE_CLASS}>
          From {LOOKBACK_HOURS} hours ago to the next {calendar.window_hours} hours, UTC.
        </p>
        <RiskBadge risk={calendar.immediate_risk} status={calendar.calendar_status} />
      </CardHeader>
      <CardContent className="space-y-3">
        <Body calendar={calendar} />
      </CardContent>
    </Card>
  );
}

/** The card, or one small note when the calendar call failed; never hides the page around it. */
export function CalendarSlot({ result }: { result: CalendarResult }) {
  if (result.success) return <CalendarCard calendar={result.data} />;
  return (
    <p role="status" className="rounded-lg border p-3 text-sm text-muted-foreground">
      Economic calendar not loaded: {result.error}
    </p>
  );
}
