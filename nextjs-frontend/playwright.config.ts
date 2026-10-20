import net from 'node:net';
import { defineConfig, devices } from '@playwright/test';

/**
 * Local-only end-to-end suite (CI does not run it): `npm run test:e2e`. It builds the production
 * bundle, starts it next to a deterministic stub of the scanner API (e2e/stub-backend.mjs) and
 * drives Chromium. No MT5, no AI provider, no network beyond loopback.
 */

const INTERNAL_KEY = 'e2e-internal-key';

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as net.AddressInfo;
      server.close(() => resolve(port));
    });
  });
}

// Pick the ports once, in the main process. Workers re-evaluate this file and inherit the env.
process.env.E2E_PORT ??= String(await freePort());
process.env.E2E_API_PORT ??= String(await freePort());
const webUrl = `http://127.0.0.1:${process.env.E2E_PORT}`;
const apiUrl = `http://127.0.0.1:${process.env.E2E_API_PORT}`;
process.env.E2E_API_URL = apiUrl;
process.env.E2E_INTERNAL_KEY = INTERNAL_KEY;

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  // The specs share one in-memory stub, so they run one at a time.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  timeout: 30_000,
  expect: { timeout: 10_000 },
  outputDir: 'test-results',
  use: {
    baseURL: webUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'node e2e/stub-backend.mjs',
      url: `${apiUrl}/health`,
      reuseExistingServer: false,
      timeout: 15_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: { E2E_API_PORT: process.env.E2E_API_PORT, E2E_INTERNAL_KEY: INTERNAL_KEY },
    },
    {
      command: 'node e2e/serve-web.mjs',
      url: webUrl,
      reuseExistingServer: false,
      timeout: 300_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: {
        BACKEND_API_URL: apiUrl,
        BACKEND_INTERNAL_KEY: INTERNAL_KEY,
        E2E_PORT: process.env.E2E_PORT,
        NODE_ENV: 'production',
        NEXT_TELEMETRY_DISABLED: '1',
      },
    },
  ],
});
