import { defineConfig } from '@hey-api/openapi-ts';

// Generates the typed fetch client from the backend's OpenAPI schema (ADR-008, KAN-33).
// Refresh the schema first with `uv run python -m commands.generate_openapi_schema`
// (see fastapi_backend/), then run `npm run generate:client`.
export default defineConfig({
  input: './openapi.json',
  output: {
    path: './src/lib/api/generated',
    // No post-processing (prettier/eslint): output must be identical on every machine.
    // The directory is ignored by eslint and prettier instead.
  },
  plugins: ['@hey-api/client-fetch', '@hey-api/typescript', '@hey-api/sdk'],
});
