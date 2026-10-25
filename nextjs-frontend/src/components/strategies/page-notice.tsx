'use client';

import { useEffect, useRef, type ReactNode } from 'react';

/**
 * A one-off outcome on the list page ("Saved", "Deleted") after a redirect. It takes focus when it
 * appears, so screen readers read it and keyboard focus lands somewhere that stays.
 */
export function PageNotice({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  return (
    <p
      ref={ref}
      role="status"
      tabIndex={-1}
      className="rounded-lg border p-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {children}
    </p>
  );
}
