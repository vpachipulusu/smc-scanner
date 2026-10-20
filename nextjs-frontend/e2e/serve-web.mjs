// Builds the production bundle and serves it for the Playwright suite. Never `next dev`: its
// first-request compiles make timings flaky. Set E2E_SKIP_BUILD=1 to reuse an existing build.
import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const nextBin = require.resolve('next/dist/bin/next');
const port = process.env.E2E_PORT;

if (!port) throw new Error('E2E_PORT is not set');

if (process.env.E2E_SKIP_BUILD) {
  console.warn('E2E_SKIP_BUILD is set: serving the existing .next build, which may be stale.');
} else {
  const build = spawnSync(process.execPath, [nextBin, 'build'], { stdio: 'inherit' });
  if (build.status !== 0) process.exit(build.status ?? 1);
}

const server = spawn(process.execPath, [nextBin, 'start', '-p', port, '-H', '127.0.0.1'], {
  stdio: 'inherit',
});
server.on('exit', (code) => process.exit(code ?? 1));

// Windows has no SIGTERM semantics: kill the whole tree so no server outlives the run.
function stopServer() {
  if (server.exitCode !== null || server.pid === undefined) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(server.pid), '/T', '/F'], { stdio: 'ignore' });
  } else {
    server.kill('SIGTERM');
  }
}
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    stopServer();
    process.exit(0);
  });
}
process.on('exit', stopServer);
