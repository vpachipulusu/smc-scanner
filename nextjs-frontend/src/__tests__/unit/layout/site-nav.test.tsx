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

  it('links Automation and Settings', () => {
    render(<SiteNav />);

    expect(screen.getByRole('link', { name: 'Automation' })).toHaveAttribute('href', '/automation');
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings');
  });

  it('links Strategies and marks it current on /strategies and below', () => {
    nav.pathname = '/strategies/my-setup/edit';
    render(<SiteNav />);

    const link = screen.getByRole('link', { name: 'Strategies' });
    expect(link).toHaveAttribute('href', '/strategies');
    expect(link).toHaveAttribute('aria-current', 'page');
  });

  it('marks Settings as current on /settings', () => {
    nav.pathname = '/settings';
    render(<SiteNav />);

    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Automation' })).not.toHaveAttribute('aria-current');
  });

  it('is keyboard reachable in order', async () => {
    render(<SiteNav />);

    await userEvent.tab();
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole('link', { name: 'Scan' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole('link', { name: 'Strategies' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole('link', { name: 'Analyses' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole('link', { name: 'Journal' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole('link', { name: 'Automation' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole('button', { name: /theme/ })).toHaveFocus();
  });

  it('links Journal and marks it current on /journal and below', () => {
    nav.pathname = '/journal/new';
    render(<SiteNav />);

    expect(screen.getByRole('link', { name: 'Journal' })).toHaveAttribute('href', '/journal');
    expect(screen.getByRole('link', { name: 'Journal' })).toHaveAttribute('aria-current', 'page');
  });

  it('links Analyses and marks it current on /analyses and below', () => {
    nav.pathname = '/analyses/42';
    render(<SiteNav />);

    expect(screen.getByRole('link', { name: 'Analyses' })).toHaveAttribute('href', '/analyses');
    expect(screen.getByRole('link', { name: 'Analyses' })).toHaveAttribute('aria-current', 'page');
  });
});
