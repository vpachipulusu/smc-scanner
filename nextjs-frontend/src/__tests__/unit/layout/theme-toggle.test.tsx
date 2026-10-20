import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeToggle } from '@/components/layout/theme-toggle';
import { THEME_STORAGE_KEY, themeInitScript } from '@/lib/theme';

function mockPrefersDark(matches: boolean) {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches }));
}

describe('ThemeToggle', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = '';
    delete document.documentElement.dataset.theme;
    mockPrefersDark(false);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('starts light and switches to dark, persisting the choice', async () => {
    render(<ThemeToggle />);

    await userEvent.click(await screen.findByRole('button', { name: 'Switch to dark theme' }));

    expect(document.documentElement).toHaveClass('dark');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeInTheDocument();
  });

  it('switches back to light', async () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    render(<ThemeToggle />);

    await userEvent.click(await screen.findByRole('button', { name: 'Switch to light theme' }));

    expect(document.documentElement).not.toHaveClass('dark');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
  });

  it('respects prefers-color-scheme when nothing is stored', async () => {
    mockPrefersDark(true);
    render(<ThemeToggle />);

    expect(
      await screen.findByRole('button', { name: 'Switch to light theme' })
    ).toBeInTheDocument();
  });

  it('prefers the stored choice over the system', async () => {
    mockPrefersDark(true);
    localStorage.setItem(THEME_STORAGE_KEY, 'light');
    render(<ThemeToggle />);

    expect(await screen.findByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument();
  });

  it('still toggles when localStorage throws', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    render(<ThemeToggle />);

    await userEvent.click(await screen.findByRole('button', { name: 'Switch to dark theme' }));

    expect(document.documentElement).toHaveClass('dark');
  });

  it('follows a theme change made in another tab', async () => {
    render(<ThemeToggle />);
    await screen.findByRole('button', { name: 'Switch to dark theme' });

    localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: THEME_STORAGE_KEY }));
    });

    expect(
      await screen.findByRole('button', { name: 'Switch to light theme' })
    ).toBeInTheDocument();
    expect(document.documentElement).toHaveClass('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('ignores storage events for other keys', async () => {
    render(<ThemeToggle />);
    await screen.findByRole('button', { name: 'Switch to dark theme' });

    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: 'other' }));
    });

    expect(document.documentElement).not.toHaveClass('dark');
  });
});

describe('themeInitScript', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = '';
    delete document.documentElement.dataset.theme;
    mockPrefersDark(false);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const run = () => new Function(themeInitScript)();

  it('applies a stored dark theme', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    run();
    expect(document.documentElement).toHaveClass('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('ignores an invalid stored value and uses the system preference', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'purple');
    mockPrefersDark(true);
    run();
    expect(document.documentElement).toHaveClass('dark');
  });

  it('stays light when nothing is stored and the system is light', () => {
    run();
    expect(document.documentElement).not.toHaveClass('dark');
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('never throws when storage is blocked', () => {
    mockPrefersDark(true);
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(run).not.toThrow();
    expect(document.documentElement).toHaveClass('dark');
  });
});
