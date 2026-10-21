import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { EquityCurve } from '@/components/journal/equity-curve';
import { makeStats } from '../../helpers/journal-stats-fixtures';

describe('EquityCurve', () => {
  it('draws an accessible SVG with a text alternative table', () => {
    const html = renderToStaticMarkup(<EquityCurve points={makeStats().cumulative} />);

    expect(html).toContain('<svg');
    expect(html).toContain('role="img"');
    const labelledBy = /aria-labelledby="([^"]+)"/.exec(html)?.[1] ?? '';
    for (const id of labelledBy.split(' ')) {
      expect(html).toContain(`id="${id}"`);
    }
    expect(html).toContain('<path');
    expect(html).toContain('sr-only');
    expect(html).toContain('<table');
    expect(html).toContain('+3.00R');
  });

  it('gives each instance its own ids', () => {
    const one = renderToStaticMarkup(
      <>
        <EquityCurve points={makeStats().cumulative} />
        <EquityCurve points={makeStats().cumulative} />
      </>
    );
    const ids = [...one.matchAll(/<title id="([^"]+)"/g)].map((m) => m[1]);
    expect(ids).toHaveLength(2);
    expect(new Set(ids).size).toBe(2);
  });

  it('renders nothing without points', () => {
    expect(renderToStaticMarkup(<EquityCurve points={[]} />)).toBe('');
  });

  it('thins a very long series but keeps the last value in the table', () => {
    const points = Array.from({ length: 1500 }, (_, i) => ({
      entry_id: i + 1,
      closed_at: '2026-10-20T10:00:00Z',
      r: 1,
      cumulative_r: i + 1,
    }));
    const html = renderToStaticMarkup(<EquityCurve points={points} />);

    expect((html.match(/<tr>/g) ?? []).length).toBeLessThanOrEqual(502);
    expect(html).toContain('+1500.00R');
  });
});
