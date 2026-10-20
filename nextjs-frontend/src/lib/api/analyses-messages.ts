/**
 * Fixed messages for failed analyses requests. No `server-only` here so presentational components
 * can import them. The API's own error text is never passed on. Developer hints (commands, env
 * var names) are added only outside production.
 */

export const ANALYSES_UNAVAILABLE_MESSAGE = 'The scanner API could not be reached.';
export const ANALYSES_UNAVAILABLE_HINT = ' Start it with `uv run uvicorn smc_scanner.api:app`.';
export const ANALYSES_UNAUTHORIZED_MESSAGE = 'The scanner API rejected the internal key.';
export const ANALYSES_UNAUTHORIZED_HINT = ' BACKEND_INTERNAL_KEY must equal SMC_INTERNAL_KEY.';
export const ANALYSIS_NOT_FOUND_MESSAGE = 'No analysis with that id.';
export const ANALYSES_REQUEST_FAILED_MESSAGE = 'The analyses request failed. Please try again.';

function withHint(message: string, hint: string): string {
  return process.env.NODE_ENV === 'production' ? message : `${message}${hint}`;
}

/** The message for an unreachable API; carries the start command outside production. */
export function analysesUnavailableMessage(): string {
  return withHint(ANALYSES_UNAVAILABLE_MESSAGE, ANALYSES_UNAVAILABLE_HINT);
}

/** The message for a failed result. Never echoes the backend's text. */
export function analysesErrorMessage(result: { error: string; status?: number }): string {
  switch (result.status) {
    case undefined:
      return analysesUnavailableMessage();
    case 401:
      return withHint(ANALYSES_UNAUTHORIZED_MESSAGE, ANALYSES_UNAUTHORIZED_HINT);
    case 404:
      return ANALYSIS_NOT_FOUND_MESSAGE;
    default:
      return ANALYSES_REQUEST_FAILED_MESSAGE;
  }
}
