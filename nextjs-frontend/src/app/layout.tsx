import type { Metadata } from 'next';
import Link from 'next/link';
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
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <header className="border-b">
          <div className="container flex h-14 items-center justify-between gap-4">
            <Link href="/scan" className="font-semibold tracking-tight">
              SMC scanner
            </Link>
            <p className="text-sm text-muted-foreground">Screening only. It never places trades.</p>
          </div>
        </header>
        <main id="main-content" className="container py-6">
          {children}
        </main>
      </body>
    </html>
  );
}
