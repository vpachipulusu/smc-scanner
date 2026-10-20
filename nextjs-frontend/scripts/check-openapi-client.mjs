// Fails when src/lib/api/generated is out of date with openapi.json (KAN-33, ADR-008).
// Generates the client into a temp directory and compares it, byte for byte (ignoring CRLF),
// with the committed copy. Works the same on a clean CI checkout and on a dev machine with
// staged changes. The schema itself is checked against the backend by
// fastapi_backend/commands/check_openapi_schema.py.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const committedDir = path.join(root, 'src/lib/api/generated');
const tempDir = mkdtempSync(path.join(tmpdir(), 'openapi-client-'));

function listFiles(dir, prefix = '') {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? listFiles(path.join(dir, entry.name), `${prefix}${entry.name}/`)
      : [`${prefix}${entry.name}`]
  );
}

const read = (dir, file) => readFileSync(path.join(dir, file), 'utf8').replace(/\r\n/g, '\n');

try {
  const bin = path.join(root, 'node_modules/@hey-api/openapi-ts/bin/run.js');
  execFileSync(process.execPath, [bin, '-f', 'openapi-ts.config.ts', '-o', tempDir], {
    cwd: root,
    stdio: ['ignore', 'ignore', 'inherit'],
  });

  const fresh = listFiles(tempDir).sort();
  const committed = listFiles(committedDir).sort();
  const stale = [...new Set([...fresh, ...committed])].filter(
    (file) =>
      !fresh.includes(file) ||
      !committed.includes(file) ||
      read(tempDir, file) !== read(committedDir, file)
  );

  if (stale.length > 0) {
    console.error(
      `openapi-client-check: src/lib/api/generated is out of date (${stale.join(', ')}).\n` +
        'Run `npm run generate:client` in nextjs-frontend/ and commit the result.'
    );
    process.exit(1);
  }
  console.log('openapi-client-check: src/lib/api/generated is up to date.');
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}
