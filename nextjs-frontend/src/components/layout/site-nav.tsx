'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/utils';
import { ThemeToggle } from './theme-toggle';

type NavItem = { label: string; href: string };

const LINKS: readonly NavItem[] = [
  { label: 'Dashboard', href: '/' },
  { label: 'Scan', href: '/scan' },
];

/** Pages that are not built yet. Shown, but not links, so nobody lands on a 404. */
const SOON: readonly string[] = ['Analyses', 'Automation', 'Settings'];

const ITEM_CLASS =
  'inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background';

function isActive(pathname: string, href: string): boolean {
  return href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(`${href}/`);
}

export function SiteNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Main" className="flex flex-wrap items-center gap-x-1 gap-y-1">
      <ul className="flex flex-wrap items-center gap-1">
        {LINKS.map(({ label, href }) => {
          const active = isActive(pathname, href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  ITEM_CLASS,
                  active
                    ? 'bg-secondary text-foreground underline underline-offset-4'
                    : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                )}
              >
                {label}
              </Link>
            </li>
          );
        })}
        {SOON.map((label) => (
          <li key={label}>
            <span
              aria-disabled="true"
              className={cn(ITEM_CLASS, 'cursor-not-allowed gap-1.5 text-muted-foreground')}
            >
              {label}
              <span className="sr-only"> (coming soon)</span>
              <span
                aria-hidden="true"
                className="rounded-full bg-secondary px-1.5 py-0.5 text-[0.6875rem] font-semibold uppercase leading-none text-foreground"
              >
                Soon
              </span>
            </span>
          </li>
        ))}
      </ul>
      <div className="ml-auto">
        <ThemeToggle />
      </div>
    </nav>
  );
}
