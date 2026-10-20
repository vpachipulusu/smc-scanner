'use client';

import { useSyncExternalStore } from 'react';
import { Moon, Sun } from 'lucide-react';

import { THEME_STORAGE_KEY, type Theme } from '@/lib/theme';

const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // Another tab changed the theme: apply it here too, then re-read.
  const onStorage = (event: StorageEvent) => {
    if (event.key !== THEME_STORAGE_KEY) return;
    const stored = readStoredTheme();
    if (stored) applyTheme(stored);
    listener();
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

function readStoredTheme(): Theme | null {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'dark' || stored === 'light' ? stored : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  const query =
    typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)');
  return query && query.matches ? 'dark' : 'light';
}

/** Storage first; when it is blocked, the theme applied to <html> in this page view; then the system. */
function getSnapshot(): Theme {
  const applied = document.documentElement.dataset.theme;
  return readStoredTheme() ?? (applied === 'dark' || applied === 'light' ? applied : systemTheme());
}

function getServerSnapshot(): Theme {
  return 'light';
}

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.documentElement.classList.toggle('dark', theme === 'dark');
}

function setTheme(next: Theme): void {
  applyTheme(next);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // Storage is blocked (private window): the choice still applies for this page view.
  }
  listeners.forEach((listener) => listener());
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const next: Theme = theme === 'dark' ? 'light' : 'dark';
  const Icon = theme === 'dark' ? Sun : Moon;

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} theme`}
      className="inline-flex size-10 items-center justify-center rounded-md border border-border text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <Icon aria-hidden="true" className="size-4" />
    </button>
  );
}
