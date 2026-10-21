import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { CalendarCard, CalendarSlot } from '@/components/calendar/calendar-card';
import { RiskBadge } from '@/components/calendar/risk-badge';
import { makeCalendar, makeEvent } from '../../helpers/calendar-fixtures';

describe('RiskBadge', () => {
  it.each([
    ['none', /no immediate news risk/i],
    ['elevated', /elevated news risk/i],
    ['high', /high news risk/i],
  ] as const)('shows a text label for %s risk', (risk, label) => {
    render(<RiskBadge risk={risk} status="fresh" />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText(/stale/i)).not.toBeInTheDocument();
  });

  it('adds a stale pill and keeps the risk when stale', () => {
    render(<RiskBadge risk="high" status="stale" />);
    expect(screen.getByText(/high news risk/i)).toBeInTheDocument();
    expect(screen.getByText(/data is stale/i)).toBeInTheDocument();
  });

  it('says the risk is unknown, not "no risk", when unavailable', () => {
    render(<RiskBadge risk="none" status="unavailable" />);
    expect(screen.getByText(/news risk unknown/i)).toBeInTheDocument();
    expect(screen.queryByText(/no immediate/i)).not.toBeInTheDocument();
  });
});

describe('CalendarCard', () => {
  it('lists events with figures and dashes for missing numbers', () => {
    render(<CalendarCard calendar={makeCalendar({ immediate_risk: 'elevated' })} />);
    const row = screen.getByText('Non-Farm Payrolls').closest('tr') as HTMLElement;
    const cells = within(row)
      .getAllByRole('cell')
      .map((cell) => cell.textContent);
    expect(cells).toEqual([
      '2026-10-21 12:30 UTC',
      'USD',
      'High',
      'Non-Farm Payrolls',
      '—',
      '180',
      '175.5',
    ]);
    expect(screen.getByText(/elevated news risk/i)).toBeInTheDocument();
    expect(screen.getByText(/next 24 hours/i)).toBeInTheDocument();
  });

  it('renders an untrusted title as plain truncated text', () => {
    const title = `<img src=x onerror=alert(1)> ${'y'.repeat(300)}`;
    const { container } = render(
      <CalendarCard calendar={makeCalendar({ events: [makeEvent({ title })] })} />
    );
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('a')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>');
    expect(container.textContent).toContain('…');
    expect(container.textContent).not.toContain('y'.repeat(200));
  });

  it('shows an empty state when there are no events', () => {
    render(<CalendarCard calendar={makeCalendar({ events: [] })} />);
    expect(screen.getByText(/no events in the window for EUR, USD/i)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('says so when the symbol has no currencies', () => {
    render(<CalendarCard calendar={makeCalendar({ currencies: [], events: [] })} />);
    expect(screen.getByText(/not recognised/i)).toBeInTheDocument();
  });

  it('shows the unavailable note and no table', () => {
    render(
      <CalendarCard
        calendar={makeCalendar({ calendar_status: 'unavailable', events: [], fetched_at: null })}
      />
    );
    expect(screen.getByRole('status')).toHaveTextContent(/unavailable right now/i);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows the stale note with the fetch time and still lists events', () => {
    render(<CalendarCard calendar={makeCalendar({ calendar_status: 'stale' })} />);
    expect(screen.getByRole('status')).toHaveTextContent(
      /cached data fetched 2026-10-21 09:45 UTC/i
    );
    expect(screen.getByRole('table')).toBeInTheDocument();
  });
});

describe('CalendarSlot', () => {
  it('renders the card on success', () => {
    render(<CalendarSlot result={{ success: true, data: makeCalendar() }} />);
    expect(screen.getByText('Economic calendar')).toBeInTheDocument();
  });

  it('renders a small inline note on failure', () => {
    render(<CalendarSlot result={{ success: false, error: 'Too many requests.', status: 429 }} />);
    expect(screen.getByRole('status')).toHaveTextContent(
      'Economic calendar not loaded: Too many requests.'
    );
  });
});
