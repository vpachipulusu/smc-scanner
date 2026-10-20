import type { Metadata } from 'next';
import Link from 'next/link';
import { SiteNav } from '@/components/layout/site-nav';
import { themeInitScript } from '@/lib/theme';
import './globals.css';

export const metadata: Metadata = {
  title: {
    default: 'SMC scanner',
    template: '%s | SMC scanner',
  },
  description:
    'Instruments touching or near a fresh order block or fair value gap. Screening only; never trades.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: the inline script sets the theme class and data-theme before React hydrates.
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-screen font-sans antialiased">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:ring-2 focus:ring-ring"
        >
          Skip to content
        </a>
        <header className="border-b">
          <div className="container flex flex-wrap items-center gap-x-6 gap-y-2 py-2">
            <Link
              href="/"
              className="rounded-md font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              SMC scanner
            </Link>
            <div className="min-w-0 flex-1">
              <SiteNav />
            </div>
          </div>
          <p className="container pb-2 text-xs text-muted-foreground">
            Screening only. It never places trades.
          </p>
        </header>
        <main id="main-content" className="container py-6">
          {children}
        </main>
      </body>
    </html>
  );
}
