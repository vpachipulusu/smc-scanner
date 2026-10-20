import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const nav = vi.hoisted(() => ({ pathname: '/' }));
vi.mock('next/navigation', () => ({ usePathname: () => nav.pathname }));

import { SiteNav } from '@/components/layout/site-nav';

describe('SiteNav', () => {
  beforeEach(() => {
    nav.pathname = '/';
  });

  it('is a labelled navigation landmark with Scan and Dashboard links', () => {
    render(<SiteNav />);

    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Scan' })).toHaveAttribute('href', '/scan');
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('href', '/');
  });

  it('marks Dashboard as the current page on /', () => {
    render(<SiteNav />);

    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Scan' })).not.toHaveAttribute('aria-current');
  });

  it('marks Scan as current on /scan and below', () => {
    nav.pathname = '/scan/export';
    render(<SiteNav />);

    expect(screen.getByRole('link', { name: 'Scan' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Dashboard' })).not.toHaveAttribute('aria-current');
  });

  it('shows unbuilt pages as disabled soon items, not links', () => {
    render(<SiteNav />);

    for (const name of ['Analyses', 'Automation', 'Settings']) {
      expect(screen.queryByRole('link', { name: new RegExp(name) })).not.toBeInTheDocument();
      const item = screen.getByText(name).closest('[aria-disabled="true"]');
      expect(item).not.toBeNull();
      expect(item).toHaveTextContent(/soon/i);
    }
  });

  it('is keyboard reachable in order and skips the disabled items', async () => {
    render(<SiteNav />);

    await userEvent.tab();
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole('link', { name: 'Scan' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole('button', { name: /theme/ })).toHaveFocus();
  });

  it('tells screen readers the disabled items are coming soon', () => {
    render(<SiteNav />);

    expect(screen.getByText('Analyses').closest('[aria-disabled]')).toHaveTextContent(
      'Analyses (coming soon)'
    );
  });
});
