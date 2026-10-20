import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ErrorBanner } from '@/components/dashboard/error-banner';
import { LatestVerdictsCard, toVerdictItem } from '@/components/dashboard/latest-verdicts-card';
import { PlaceholderCard } from '@/components/dashboard/placeholder-card';
import { VerdictList, type VerdictItem } from '@/components/dashboard/verdict-list';
import { analysesUnavailableMessage } from '@/lib/api/analyses-messages';
import { makeAnalysis } from '../../helpers/fixtures';

const ITEMS: VerdictItem[] = [
  {
    id: 3,
    symbol: 'EURUSD',
    tf: '1h',
    createdAt: '2026-10-19T23:05:00Z',
    action: 'BUY',
    confidence: 72,
  },
  {
    id: 2,
    symbol: 'XAUUSD',
    tf: '4h',
    createdAt: '2026-10-19T22:00:00Z',
    action: 'SELL',
    confidence: 130,
  },
  { id: 1, symbol: 'GBPUSD', tf: '1h', createdAt: 'not a date', action: 'HOLD' },
];

describe('PlaceholderCard', () => {
  it('renders an h2 title and a clearly labelled coming-soon note', () => {
    render(<PlaceholderCard title="Next scheduled run" />);

    expect(
      screen.getByRole('heading', { level: 2, name: 'Next scheduled run' })
    ).toBeInTheDocument();
    expect(screen.getByText(/Coming soon/)).toBeInTheDocument();
  });
});

describe('ErrorBanner', () => {
  it('is an alert with the message', () => {
    render(<ErrorBanner message="Nope" />);

    expect(screen.getByRole('alert')).toHaveTextContent('Nope');
  });
});

describe('VerdictList', () => {
  it('renders each verdict with an action pill, confidence bar and plain-text id', () => {
    render(<VerdictList items={ITEMS} />);

    expect(screen.getAllByRole('listitem')).toHaveLength(3);
    expect(screen.getByText('BUY')).toBeInTheDocument();
    expect(screen.getByText('SELL')).toBeInTheDocument();
    expect(screen.getAllByRole('progressbar')).toHaveLength(2);
    expect(screen.getByRole('img', { name: 'Confidence not available' })).toBeInTheDocument();
    expect(screen.getByText('72%')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByText(/not available yet/)).not.toBeInTheDocument();
    expect(document.querySelectorAll('time')).toHaveLength(2);
    expect(screen.getByText('not a date').tagName).toBe('SPAN');
    expect(screen.getByText('#3')).toBeInTheDocument();
    expect(screen.getByText('2026-10-19 23:05 UTC')).toBeInTheDocument();
    expect(screen.getByText('not a date')).toBeInTheDocument();
  });

  it('marks a failed analysis without an action pill', () => {
    render(<VerdictList items={[{ ...ITEMS[0], action: null, failed: true }]} />);

    expect(screen.getByText('Analysis failed')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('says "No verdict" for a stored analysis without one, not "failed"', () => {
    render(<VerdictList items={[{ ...ITEMS[0], action: null }]} />);

    expect(screen.getByText('No verdict')).toBeInTheDocument();
    expect(screen.queryByText('Analysis failed')).not.toBeInTheDocument();
  });

  it('shows the empty state for no items', () => {
    render(<VerdictList items={[]} />);

    expect(screen.getByText('No verdicts yet.')).toBeInTheDocument();
  });
});

describe('toVerdictItem', () => {
  it('maps an ok analysis', () => {
    expect(toVerdictItem(makeAnalysis({ id: 5 }))).toMatchObject({
      id: 5,
      symbol: 'EURUSD',
      action: 'BUY',
      confidence: 72,
    });
  });

  it('has no action for a failed analysis or a missing verdict', () => {
    expect(toVerdictItem(makeAnalysis({ status: 'failed' }))).toMatchObject({
      action: null,
      failed: true,
    });
    expect(toVerdictItem(makeAnalysis({ verdict: null }))).toMatchObject({
      action: null,
      failed: false,
    });
  });
});

describe('LatestVerdictsCard', () => {
  it('lists verdicts under an h2', () => {
    const items = [makeAnalysis({ id: 1 }), makeAnalysis({ id: 2 })];

    render(<LatestVerdictsCard result={{ success: true, data: { items } }} />);

    expect(screen.getByRole('heading', { level: 2, name: 'Latest verdicts' })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('shows at most ten rows', () => {
    const items = Array.from({ length: 12 }, (_, i) => makeAnalysis({ id: i + 1 }));

    render(<LatestVerdictsCard result={{ success: true, data: { items } }} />);

    expect(screen.getAllByRole('listitem')).toHaveLength(10);
  });

  it('shows the empty state', () => {
    render(<LatestVerdictsCard result={{ success: true, data: { items: [] } }} />);

    expect(screen.getByText('No verdicts yet.')).toBeInTheDocument();
  });

  it('shows a safe alert on failure', () => {
    render(<LatestVerdictsCard result={{ success: false, error: 'raw secret trace' }} />);

    expect(screen.getByRole('alert')).toHaveTextContent(analysesUnavailableMessage());
    expect(screen.queryByText(/secret/)).not.toBeInTheDocument();
  });
});
