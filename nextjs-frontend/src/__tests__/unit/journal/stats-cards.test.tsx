import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { JournalStatsCards } from '@/components/journal/journal-stats-cards';
import { NO_VALUE } from '@/lib/journal/format';
import { makeEmptyStats, makeStats } from '../../helpers/journal-stats-fixtures';

describe('JournalStatsCards', () => {
  it('shows the headline numbers and the open trade count', () => {
    const html = renderToStaticMarkup(<JournalStatsCards summary={makeStats().summary} />);

    expect(html).toContain('Win rate');
    expect(html).toContain('50%');
    expect(html).toContain('+0.75R');
    expect(html).toContain('+3.00R');
    expect(html).toContain('-1.00R');
    expect(html).toContain('Open trades');
    expect(html).toMatch(/Open trades[\s\S]*?>2</);
    expect(html).not.toContain('No closed trades yet');
  });

  it('shows the placeholder and a note when nothing is closed', () => {
    const html = renderToStaticMarkup(<JournalStatsCards summary={makeEmptyStats().summary} />);

    expect(html).toContain('No closed trades yet');
    expect(html).toContain(NO_VALUE);
    expect(html).not.toContain('NaN');
    expect(html).not.toContain('0.00R');
    expect(html).toMatch(/Open trades[\s\S]*?>3</);
  });

  it('never prints a non-finite number', () => {
    const html = renderToStaticMarkup(
      <JournalStatsCards
        summary={makeStats({ win_rate: Number.NaN, average_r: Number.POSITIVE_INFINITY }).summary}
      />
    );

    expect(html).not.toContain('NaN');
    expect(html).not.toContain('Infinity');
  });
});
