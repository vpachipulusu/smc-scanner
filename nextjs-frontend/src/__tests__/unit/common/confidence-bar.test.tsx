import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ConfidenceBar } from '@/components/common/confidence-bar';

describe('ConfidenceBar', () => {
  it('exposes a progressbar with value, range and visible text', () => {
    render(<ConfidenceBar value={72} />);

    const bar = screen.getByRole('progressbar', { name: 'Confidence' });
    expect(bar).toHaveAttribute('aria-valuenow', '72');
    expect(bar).toHaveAttribute('aria-valuemin', '0');
    expect(bar).toHaveAttribute('aria-valuemax', '100');
    expect(screen.getByText('72%')).toBeVisible();
  });

  it.each([
    [150, 100],
    [-5, 0],
  ])('clamps %s to %s', (input, expected) => {
    render(<ConfidenceBar value={input} />);

    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', String(expected));
    expect(screen.getByText(`${expected}%`)).toBeInTheDocument();
  });

  it('rounds fractional values', () => {
    render(<ConfidenceBar value={71.6} />);

    expect(screen.getByText('72%')).toBeInTheDocument();
  });

  it.each([[undefined], [null], [Number.NaN], [Infinity]])('shows N/A for %s', (value) => {
    render(<ConfidenceBar value={value as number | undefined} />);

    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Confidence not available' })).toBeInTheDocument();
    expect(screen.getByText('N/A')).toBeInTheDocument();
  });

  it('accepts a custom label', () => {
    render(<ConfidenceBar value={10} label="Verdict confidence" />);

    expect(screen.getByRole('progressbar', { name: 'Verdict confidence' })).toBeInTheDocument();
  });
});
