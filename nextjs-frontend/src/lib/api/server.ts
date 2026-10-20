import 'server-only';

import { createClient, createConfig, type Client } from './generated/client';

/**
 * Server-only entry point to the scanner API, trimmed from StoreCart's `callBackend`: no session
 * cookie here (the scanner has no users), only the base URL and the optional shared key. Generated
 * SDK calls go through `callBackend`, which folds every outcome into the `{ success, ... }` envelope.
 * The browser never calls the API, and nothing here reaches a client bundle.
 */

export const INTERNAL_KEY_HEADER = 'X-Internal-Key';

export const BACKEND_UNAVAILABLE_MESSAGE = 'Backend unavailable';
export const BACKEND_ERROR_MESSAGE = 'Request failed';

/** `status` is the API's HTTP status when it answered (absent when it was unreachable). */
export type ApiResult<T> =
  { success: true; data: T } | { success: false; error: string; status?: number };

type SdkResult<TData> = { data?: TData; error?: unknown; response?: Response };

export class BackendNotConfiguredError extends Error {
  constructor(variable: string) {
    super(`${variable} is not set`);
    this.name = 'BackendNotConfiguredError';
  }
}

function getBackendUrl(): string {
  const url = process.env.BACKEND_API_URL;
  if (!url) {
    throw new BackendNotConfiguredError('BACKEND_API_URL');
  }
  return url.replace(/\/+$/, '');
}

/** A fresh client per call; the key is read at call time so tests can stub the environment. */
export function getBackendClient(): Client {
  const internalKey = process.env.BACKEND_INTERNAL_KEY;
  return createClient(
    createConfig({
      baseUrl: getBackendUrl(),
      cache: 'no-store',
      headers: internalKey ? { [INTERNAL_KEY_HEADER]: internalKey } : {},
    })
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** The API's error envelope is `{ success: false, error: string }`. */
function errorMessage(error: unknown): string {
  if (isRecord(error) && error.success === false && typeof error.error === 'string') {
    return error.error;
  }
  return BACKEND_ERROR_MESSAGE;
}

export async function callBackend<TData>(
  call: (client: Client) => Promise<SdkResult<TData>>
): Promise<ApiResult<TData>> {
  let client: Client;
  try {
    client = getBackendClient();
  } catch (error) {
    if (error instanceof BackendNotConfiguredError) {
      return { success: false, error: BACKEND_UNAVAILABLE_MESSAGE };
    }
    throw error;
  }
  let result: SdkResult<TData>;
  try {
    result = await call(client);
  } catch {
    return { success: false, error: BACKEND_UNAVAILABLE_MESSAGE };
  }

  // The generated client reports a failed fetch (no response) through `error`, not by throwing.
  if (result.error !== undefined && !result.response) {
    return { success: false, error: BACKEND_UNAVAILABLE_MESSAGE };
  }
  if (result.error !== undefined || (result.response && !result.response.ok)) {
    return { success: false, error: errorMessage(result.error), status: result.response?.status };
  }
  if (result.data === undefined) {
    return { success: false, error: BACKEND_ERROR_MESSAGE, status: result.response?.status };
  }
  return { success: true, data: result.data };
}
