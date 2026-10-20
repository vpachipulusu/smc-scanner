import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

afterEach(() => {
  cleanup();
});

// server-only throws outside a Server Component; unit tests import its guarded modules directly.
vi.mock('server-only', () => ({}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
  }),
  usePathname: () => '/scan',
  useSearchParams: () => new URLSearchParams(),
  redirect: vi.fn(),
}));
