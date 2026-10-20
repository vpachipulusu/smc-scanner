// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import RootLayout from '@/app/layout';
import { themeInitScript } from '@/lib/theme';

describe('RootLayout', () => {
  const html = renderToStaticMarkup(
    <RootLayout>
      <p>content</p>
    </RootLayout>
  );

  it('inlines the theme init script in the head', () => {
    expect(html).toContain(`<head><script>${themeInitScript}</script></head>`);
  });

  it('has header, nav and main landmarks around the page content', () => {
    expect(html).toContain('<header');
    expect(html).toContain('aria-label="Main"');
    expect(html).toMatch(/<main id="main-content"[^>]*><p>content<\/p><\/main>/);
  });
});
