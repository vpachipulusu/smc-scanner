import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { HistoryFilters } from '@/components/analyses/history/history-filters';
import { HistoryPager } from '@/components/analyses/history/history-pager';
import { HistoryTable } from '@/components/analyses/history/history-table';
import { HistoryError } from '@/components/analyses/history/history-error';
import { makeAnalysis } from '../../helpers/fixtures';

describe('HistoryFilters', () => {
  it('is a GET search form with labelled, prefilled controls', () => {
    render(<HistoryFilters params={{ symbol: 'EURUSD', action: 'SELL', minConfidence: 60 }} />);
    const form = screen.getByRole('search', { name: 'Filter analyses' });
    expect(form).toHaveAttribute('action', '/analyses');
    expect(form).toHaveAttribute('method', 'get');
    expect(screen.getByLabelText('Symbol')).toHaveValue('EURUSD');
    expect(screen.getByLabelText('Action')).toHaveValue('SELL');
    expect(screen.getByLabelText('Min confidence')).toHaveValue(60);
    expect(screen.getByRole('link', { name: 'Reset' })).toHaveAttribute('href', '/analyses');
  });

  it('omits Reset when no filter is set', () => {
    render(<HistoryFilters params={{}} />);
    expect(screen.queryByRole('link', { name: 'Reset' })).toBeNull();
    expect(screen.getByLabelText('Action')).toHaveValue('');
  });
});

describe('HistoryTable', () => {
  it('shows the columns and links each row to its detail page', () => {
    render(
      <HistoryTable
        items={[makeAnalysis({ id: 42, verdict: { action: 'BUY', confidence: 72, quality: 'A' } })]}
      />
    );
    for (const name of [
      'Time',
      'Symbol',
      'TF',
      'Action',
      'Confidence',
      'Quality',
      'Zone',
      'Provider',
    ]) {
      expect(screen.getByRole('columnheader', { name })).toBeInTheDocument();
    }
    const row = screen.getAllByRole('row')[1];
    expect(within(row).getByRole('link')).toHaveAttribute('href', '/analyses/42');
    expect(within(row).getByText('EURUSD')).toBeInTheDocument();
    expect(within(row).getByText('BUY')).toBeInTheDocument();
    expect(within(row).getByText('A')).toBeInTheDocument();
    expect(within(row).getByText('anthropic')).toBeInTheDocument();
    expect(within(row).getByText('2026-10-19 23:05 UTC')).toBeInTheDocument();
  });

  it('labels failed and verdict-less analyses', () => {
    render(
      <HistoryTable
        items={[
          makeAnalysis({ id: 1, status: 'failed', verdict: null }),
          makeAnalysis({ id: 2, status: 'ok', verdict: null }),
        ]}
      />
    );
    expect(screen.getByText('Analysis failed')).toBeInTheDocument();
    expect(screen.getByText('No verdict')).toBeInTheDocument();
  });

  it('renders text as text, never markup', () => {
    const { container } = render(
      <HistoryTable items={[makeAnalysis({ symbol: '<img src=x onerror=alert(1)>' })]} />
    );
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
  });
});

describe('HistoryPager', () => {
  it('links to the next page keeping the filters, and back to the first', () => {
    render(<HistoryPager params={{ symbol: 'EURUSD', cursor: 'abc=' }} nextCursor="def=" />);
    expect(screen.getByRole('link', { name: 'Older' })).toHaveAttribute(
      'href',
      '/analyses?symbol=EURUSD&cursor=def%3D'
    );
    expect(screen.getByRole('link', { name: 'Newest' })).toHaveAttribute(
      'href',
      '/analyses?symbol=EURUSD'
    );
  });

  it('renders nothing on a single page', () => {
    const { container } = render(<HistoryPager params={{}} nextCursor={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows only Newest on the last page', () => {
    render(<HistoryPager params={{ cursor: 'abc=' }} nextCursor={null} />);
    expect(screen.queryByRole('link', { name: 'Older' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Newest' })).toHaveAttribute('href', '/analyses');
  });
});

describe('HistoryError', () => {
  it('is an alert with the message and a retry link to the same filters', () => {
    render(<HistoryError message="The analyses request failed." retryHref="/analyses?symbol=X" />);
    expect(screen.getByRole('alert')).toHaveTextContent('The analyses request failed.');
    expect(screen.getByRole('link', { name: 'Retry' })).toHaveAttribute(
      'href',
      '/analyses?symbol=X'
    );
  });
});
