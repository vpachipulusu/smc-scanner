/** The stored-analysis view of multi-timeframe context. */
import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { AnalysisDetail } from '@/components/analyses/analysis-detail';
import { MtfContext } from '@/components/analyses/mtf-context';
import { makeAnalysis } from '../../helpers/fixtures';

describe('MtfContext', () => {
  it('lists the timeframes used and the higher timeframe', () => {
    render(
      <MtfContext analysis={makeAnalysis({ tf: '1h', timeframes_used: ['1h', '4h', '30m'] })} />
    );

    const section = screen.getByRole('region', { name: 'Timeframes' });
    expect(within(section).getByText('Timeframes used')).toBeInTheDocument();
    expect(within(section).getByText('1h, 4h, 30m')).toBeInTheDocument();
    expect(within(section).getByText('Higher timeframe')).toBeInTheDocument();
    expect(within(section).getByText('4h')).toBeInTheDocument();
    expect(section).toHaveTextContent('not part of the 0-4 score');
  });

  it('says n/a when there is no higher timeframe, as on 1d', () => {
    render(<MtfContext analysis={makeAnalysis({ tf: '1d', timeframes_used: ['1d', '4h'] })} />);

    const section = screen.getByRole('region', { name: 'Timeframes' });
    expect(within(section).getByText('n/a')).toBeInTheDocument();
  });

  it('shows the scan timeframe alone for a single-timeframe analysis', () => {
    render(<MtfContext analysis={makeAnalysis({ tf: '1h', timeframes_used: ['1h'] })} />);

    expect(screen.getByText('1h')).toBeInTheDocument();
    expect(screen.getByText('n/a')).toBeInTheDocument();
  });

  it('copes with a missing list', () => {
    const missing = makeAnalysis({ timeframes_used: undefined as unknown as string[] });
    render(<MtfContext analysis={missing} />);

    expect(screen.getAllByText('n/a')).toHaveLength(2);
  });

  it('drops unknown names instead of rendering them', () => {
    render(
      <MtfContext analysis={makeAnalysis({ tf: '1h', timeframes_used: ['1h', '<img src=x>'] })} />
    );

    expect(document.querySelector('img')).toBeNull();
    expect(screen.queryByText(/<img/)).not.toBeInTheDocument();
  });

  it('appears on the analysis detail page', () => {
    render(<AnalysisDetail analysis={makeAnalysis({ tf: '1h', timeframes_used: ['1h', '4h'] })} />);

    expect(screen.getByRole('region', { name: 'Timeframes' })).toBeInTheDocument();
  });
});
