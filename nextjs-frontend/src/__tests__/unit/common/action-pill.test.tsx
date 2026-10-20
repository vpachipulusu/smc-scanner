import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ActionPill } from '@/components/common/action-pill';

describe('ActionPill', () => {
  it.each([
    ['BUY', 'bg-good'],
    ['SELL', 'bg-crit'],
    ['HOLD', 'bg-secondary'],
  ] as const)('renders %s with its variant and a decorative icon', (action, cls) => {
    const { container } = render(<ActionPill action={action} />);

    const pill = screen.getByText(action).closest('span');
    expect(pill).toHaveClass(cls);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('falls back to a neutral pill for an unknown action', () => {
    render(<ActionPill action={'WAIT' as never} />);

    expect(screen.getByText('WAIT').closest('span')).toHaveClass('bg-secondary');
  });
});
