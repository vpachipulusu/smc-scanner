'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/utils';
import { ThemeToggle } from './theme-toggle';

type NavItem = { label: string; href: string };

const LINKS: readonly NavItem[] = [
  { label: 'Dashboard', href: '/' },
  { label: 'Scan', href: '/scan' },
  { label: 'Analyses', href: '/analyses' },
  { label: 'Automation', href: '/automation' },
  { label: 'Settings', href: '/settings' },
];

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
      </ul>
      <div className="ml-auto">
        <ThemeToggle />
      </div>
    </nav>
  );
}
