/**
 * The journal page reads one search param: the cursor for the next (older) page. It goes straight
 * back to the API, so only urlsafe-base64 text of at most 96 characters (the API's limit) is kept.
 */

export const JOURNAL_PAGE_SIZE = 25;

const CURSOR_PATTERN = /^[A-Za-z0-9_=-]{1,96}$/;

export function parseJournalCursor(raw: string | string[] | undefined): string | undefined {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value !== undefined && CURSOR_PATTERN.test(value) ? value : undefined;
}

export function journalHref(cursor?: string): string {
  return cursor ? `/journal?${new URLSearchParams({ cursor }).toString()}` : '/journal';
}
