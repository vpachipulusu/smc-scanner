import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { AnalysisDetail } from '@/components/analyses/analysis-detail';
import { AnalysisLoadError } from '@/components/analyses/analysis-load-error';
import { SetupChart } from '@/components/analyses/setup-chart';
import { TradeSetupCard } from '@/components/analyses/trade-setup-card';
import { makeAnalysis } from '../../helpers/fixtures';

const FULL = makeAnalysis({
  id: 9,
  verdict: {
    action: 'BUY',
    confidence: 72,
    quality: 'A',
    entry: 1.0975,
    stop: 1.0955,
    targets: [1.1005, 1.104],
    risk_reward: 2.5,
    invalidation: 1.095,
    reasons: ['Sweep of the low', '<script>alert(1)</script>'],
    summary: 'Long from the FVG.',
  },
});

describe('AnalysisDetail', () => {
  it('renders every section from the analysis', () => {
    render(<AnalysisDetail analysis={FULL} />);

    expect(screen.getByRole('heading', { level: 1, name: /EURUSD/ })).toBeInTheDocument();
    expect(screen.getByText('BUY')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Confidence' })).toHaveAttribute(
      'aria-valuenow',
      '72'
    );
    expect(screen.getByText('anthropic / claude')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
    expect(screen.getByText('2026-10-19 23:05 UTC')).toBeInTheDocument();
    expect(screen.getByText('Long from the FVG.')).toBeInTheDocument();
    expect(screen.getByText('Sweep of the low')).toBeInTheDocument();
    expect(screen.getByText('bull FVG')).toBeInTheDocument();
    expect(screen.getByText(/advisory only/i)).toHaveTextContent(/no orders are placed/i);
    expect(screen.getByRole('link', { name: /back to dashboard/i })).toHaveAttribute('href', '/');
  });

  it('offers Log trade, prefilled from the analysis', () => {
    render(<AnalysisDetail analysis={FULL} />);

    const href = screen.getByRole('link', { name: 'Log trade' }).getAttribute('href') ?? '';
    const url = new URL(href, 'http://x');
    expect(url.pathname).toBe('/journal/new');
    expect(Object.fromEntries(url.searchParams)).toMatchObject({
      symbol: 'EURUSD',
      side: 'long',
      entry: '1.0975',
      stop: '1.0955',
      analysis_id: '9',
    });
  });

  it('escapes reason text instead of injecting markup', () => {
    const { container } = render(<AnalysisDetail analysis={FULL} />);

    expect(screen.getByText('<script>alert(1)</script>')).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
  });

  it('shows a notice instead of a setup when the analysis failed', () => {
    render(<AnalysisDetail analysis={makeAnalysis({ status: 'failed', verdict: null })} />);

    expect(screen.getByRole('status')).toHaveTextContent(/failed/i);
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.queryByText('Entry')).not.toBeInTheDocument();
  });

  it('shows a notice when an ok analysis stored no verdict', () => {
    render(<AnalysisDetail analysis={makeAnalysis({ verdict: null })} />);

    expect(screen.getByRole('status')).toHaveTextContent(/no verdict/i);
  });

  it('shows N/A, never NaN, for missing fields', () => {
    const { container } = render(
      <AnalysisDetail
        analysis={makeAnalysis({
          bar_time: '',
          provider: '',
          model: '',
          prompt_version: '',
          zone_low: Number.NaN,
          zone_high: Number.NaN,
          verdict: { action: 'HOLD', confidence: Number.NaN },
        })}
      />
    );

    expect(container.textContent).not.toMatch(/NaN|undefined|null/);
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(3);
  });
});

describe('TradeSetupCard', () => {
  it('lists quality, entry, stop, targets, risk reward and invalidation', () => {
    render(<TradeSetupCard verdict={FULL.verdict!} />);

    const text = (label: string) => screen.getByText(label).nextElementSibling;
    expect(text('Quality')).toHaveTextContent('A');
    expect(text('Entry')).toHaveTextContent('1.0975');
    expect(text('Stop')).toHaveTextContent('1.0955');
    expect(text('Target 1')).toHaveTextContent('1.1005');
    expect(text('Target 2')).toHaveTextContent('1.104');
    expect(text('Risk : reward')).toHaveTextContent('1 : 2.5');
    expect(text('Invalidation')).toHaveTextContent('1.095');
  });

  it('uses N/A for absent levels and notes a downgrade', () => {
    render(
      <TradeSetupCard
        verdict={{ action: 'HOLD', confidence: 40, downgraded: true, downgrade_reason: 'Low R:R' }}
      />
    );

    expect(screen.getByText('Entry').nextElementSibling).toHaveTextContent('N/A');
    expect(screen.getByText('Quality').nextElementSibling).toHaveTextContent('N/A');
    expect(screen.getByText('Risk : reward').nextElementSibling).toHaveTextContent('N/A');
    expect(screen.getByText('Targets').nextElementSibling).toHaveTextContent('N/A');
    expect(screen.getByText(/downgraded/i)).toHaveTextContent('Low R:R');
  });
});

describe('SetupChart', () => {
  it('draws the levels with a text alternative listing each one', () => {
    render(<SetupChart analysis={FULL} verdict={FULL.verdict!} />);

    const chart = screen.getByRole('img');
    const description = within(document.body).getByText(/zone .*1\.0971.*1\.09898/i);
    expect(chart).toHaveAccessibleName(/EURUSD/);
    expect(chart).toHaveAccessibleDescription(description.textContent ?? '');
    expect(description).toHaveTextContent(/entry 1\.0975/i);
    expect(description).toHaveTextContent(/stop 1\.0955/i);
    expect(description).toHaveTextContent(/target 1\.1005/i);
  });

  it('draws only the zone when the verdict has no levels', () => {
    render(<SetupChart analysis={makeAnalysis()} verdict={{ action: 'HOLD', confidence: 10 }} />);

    expect(screen.getByRole('img')).toBeInTheDocument();
    expect(screen.queryByText(/entry/i)).not.toBeInTheDocument();
  });

  it('renders nothing when there is nothing finite to plot', () => {
    const { container } = render(
      <SetupChart
        analysis={makeAnalysis({ zone_low: Number.NaN, zone_high: Number.NaN })}
        verdict={{ action: 'HOLD', confidence: 10 }}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('copes with a flat range', () => {
    render(
      <SetupChart
        analysis={makeAnalysis({ zone_low: 1, zone_high: 1 })}
        verdict={{ action: 'HOLD', confidence: 10 }}
      />
    );

    expect(screen.getByRole('img')).toBeInTheDocument();
  });
});

describe('AnalysisLoadError', () => {
  it('shows the fixed message as an alert with a retry link', () => {
    render(<AnalysisLoadError message="The analyses request failed. Please try again." id={5} />);

    expect(screen.getByRole('alert')).toHaveTextContent('The analyses request failed.');
    expect(screen.getByRole('link', { name: 'Retry' })).toHaveAttribute('href', '/analyses/5');
  });
});
