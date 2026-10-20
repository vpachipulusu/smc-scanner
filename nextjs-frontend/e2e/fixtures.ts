import { test as base, expect } from '@playwright/test';

/**
 * Every test starts from the stub's seed: the stub keeps schedules and analyses in memory, so a
 * test that creates or deletes data must not leak into the next one.
 */
export const test = base.extend<{ stubReset: void }>({
  stubReset: [
    async ({ request }, use) => {
      const apiUrl = process.env.E2E_API_URL;
      if (!apiUrl)
        throw new Error('E2E_API_URL is not set; run the suite through playwright.config.ts');
      const response = await request.post(`${apiUrl}/__reset`, {
        headers: { 'x-internal-key': process.env.E2E_INTERNAL_KEY ?? '' },
      });
      expect(response.ok()).toBe(true);
      await use();
    },
    { auto: true },
  ],
});

export { expect };
