import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AnalysisDetail } from '@/components/analyses/analysis-detail';
import {
  formatPrice,
  formatUtc,
  isFiniteNumber,
  numberList,
  parseAnalysisId,
  stringList,
  textOrNA,
} from '@/components/analyses/format';
import { SetupChart } from '@/components/analyses/setup-chart';
import { makeAnalysis } from '../../helpers/fixtures';

describe('format edge cases', () => {
  it('accepts the int32 boundary and rejects one above it', () => {
    expect(parseAnalysisId('2147483647')).toBe(2147483647);
    expect(parseAnalysisId('2147483648')).toBeNull();
    expect(parseAnalysisId('9007199254740993')).toBeNull();
    expect(parseAnalysisId('+1')).toBeNull();
    expect(parseAnalysisId('1\n')).toBeNull();
    expect(parseAnalysisId('１２')).toBeNull();
  });

  it('formats zero, negatives and trailing zeros', () => {
    expect(formatPrice(0)).toBe('0');
    expect(formatPrice(1.5)).toBe('1.5');
    expect(formatPrice(-1.25)).toBe('-1.25');
    expect(formatPrice(-2345.678)).toBe('-2345.68');
  });

  it('formats offsets, fractional seconds and date-only text', () => {
    expect(formatUtc('2026-10-19T23:05:00+02:00')).toBe('2026-10-19 21:05 UTC');
    expect(formatUtc('2026-10-19T23:05:00.123Z')).toBe('2026-10-19 23:05 UTC');
    expect(formatUtc('2026-10-19')).toBe('2026-10-19 00:00 UTC');
  });

  it('filters lists and text defensively', () => {
    expect(isFiniteNumber(1)).toBe(true);
    expect(isFiniteNumber('1')).toBe(false);
    expect(stringList(['a', ' ', 3, null])).toEqual(['a']);
    expect(stringList('nope')).toEqual([]);
    expect(numberList([1, Number.NaN, '2', 3])).toEqual([1, 3]);
    expect(numberList({})).toEqual([]);
    expect(textOrNA('  ')).toBe('N/A');
    expect(textOrNA('A')).toBe('A');
  });
});

describe('malformed verdict fields', () => {
  it('renders without crashing when lists and text have the wrong type', () => {
    const verdict = {
      action: 'BUY',
      confidence: 50,
      reasons: 'not a list',
      targets: 'nope',
      summary: { a: 1 },
      quality: '',
    } as unknown as NonNullable<ReturnType<typeof makeAnalysis>['verdict']>;

    const { container } = render(<AnalysisDetail analysis={makeAnalysis({ verdict })} />);

    expect(screen.getByText('No reasons recorded.')).toBeInTheDocument();
    expect(screen.getByText('Quality').nextElementSibling).toHaveTextContent('N/A');
    expect(container.textContent).not.toMatch(/object Object/);
  });
});

describe('SetupChart', () => {
  it('orders the zone bounds when they arrive swapped', () => {
    render(
      <SetupChart
        analysis={makeAnalysis({ zone_low: 1.2, zone_high: 1.1 })}
        verdict={{ action: 'HOLD', confidence: 10 }}
      />
    );

    expect(screen.getByRole('img')).toHaveAccessibleDescription('Zone 1.1 to 1.2.');
  });

  it('keeps labels of close levels apart', () => {
    const { container } = render(
      <SetupChart
        analysis={makeAnalysis()}
        verdict={{
          action: 'BUY',
          confidence: 10,
          entry: 1.0975,
          stop: 1.0974,
          targets: [1.09745],
        }}
      />
    );

    const ys = [...container.querySelectorAll('g[aria-hidden] text')]
      .map((node) => Number(node.getAttribute('y')))
      .sort((a, b) => a - b);
    expect(ys).toHaveLength(3);
    expect(ys[1] - ys[0]).toBeGreaterThanOrEqual(13);
    expect(ys[2] - ys[1]).toBeGreaterThanOrEqual(13);
  });
});
