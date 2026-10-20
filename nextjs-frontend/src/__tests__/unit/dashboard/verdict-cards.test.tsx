import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PlaceholderCard } from '@/components/dashboard/placeholder-card';
import { VerdictList, type VerdictItem } from '@/components/dashboard/verdict-list';

const ITEMS: VerdictItem[] = [
  { instrument: 'EURUSD', action: 'BUY', confidence: 72 },
  { instrument: 'XAUUSD', action: 'SELL', confidence: 130 },
  { instrument: 'GBPUSD', action: 'HOLD' },
];

describe('PlaceholderCard', () => {
  it('renders an h2 title and the explicit empty state', () => {
    render(<PlaceholderCard title="Next scheduled run" />);

    expect(
      screen.getByRole('heading', { level: 2, name: 'Next scheduled run' })
    ).toBeInTheDocument();
    expect(
      screen.getByText('Not available yet: available after the Analyses API / scheduler land.')
    ).toBeInTheDocument();
  });
});

describe('VerdictList', () => {
  it('renders each verdict with an action pill and confidence bar', () => {
    render(<VerdictList items={ITEMS} />);

    expect(screen.getAllByRole('listitem')).toHaveLength(3);
    expect(screen.getByText('BUY')).toBeInTheDocument();
    expect(screen.getByText('SELL')).toBeInTheDocument();
    expect(screen.getAllByRole('progressbar')).toHaveLength(2);
    expect(screen.getByRole('img', { name: 'Confidence not available' })).toBeInTheDocument();
    expect(screen.getByText('72%')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByText('N/A')).toBeInTheDocument();
  });

  it('shows the empty state for no items', () => {
    render(<VerdictList items={[]} />);

    expect(screen.getByText('No verdicts yet.')).toBeInTheDocument();
  });
});
