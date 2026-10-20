/** Fixed analysis messages: no backend text, friendly 429 with the wait. */
import { describe, expect, it } from 'vitest';
import {
  ANALYSE_DISABLED_MESSAGE,
  ANALYSE_FAILED_MESSAGE,
  ANALYSE_INVALID_MESSAGE,
  ANALYSE_PROVIDER_FAILED_MESSAGE,
  ANALYSE_UNAUTHORIZED_MESSAGE,
  ANALYSE_UNAVAILABLE_MESSAGE,
  analyseErrorMessage,
  parseRetryAfter,
  rateLimitMessage,
  skipReason,
} from '@/lib/api/analyse-messages';

describe('analyseErrorMessage', () => {
  it.each([
    [undefined, ANALYSE_UNAVAILABLE_MESSAGE],
    [401, ANALYSE_UNAUTHORIZED_MESSAGE],
    [422, ANALYSE_INVALID_MESSAGE],
    [502, ANALYSE_PROVIDER_FAILED_MESSAGE],
    [503, ANALYSE_DISABLED_MESSAGE],
    [500, ANALYSE_FAILED_MESSAGE],
  ])('maps status %s to a fixed message', (status, message) => {
    expect(analyseErrorMessage({ status })).toBe(message);
  });

  it('turns 429 into a friendly message with the wait', () => {
    expect(analyseErrorMessage({ status: 429, retryAfterSeconds: 90 })).toBe(
      'The AI analysis budget or rate limit has been reached. Please try again in about 2 minutes.'
    );
  });
});

describe('rateLimitMessage', () => {
  it.each([
    [1, 'about 1 second.'],
    [30, 'about 30 seconds.'],
    [60, 'about 1 minute.'],
    [3540, 'about 59 minutes.'],
    [3600, 'about 1 hour.'],
    [3601, 'about 2 hours.'],
    [7200, 'about 2 hours.'],
  ])('words %s seconds', (seconds, text) => {
    expect(rateLimitMessage(seconds)).toContain(text);
  });

  it('asks to try later without a wait', () => {
    expect(rateLimitMessage()).toBe(
      'The AI analysis budget or rate limit has been reached. Please try again later.'
    );
  });
});

describe('parseRetryAfter', () => {
  it('reads whole seconds', () => {
    expect(parseRetryAfter('45')).toBe(45);
    expect(parseRetryAfter(' 45 ')).toBe(45);
  });

  it.each([
    null,
    undefined,
    '',
    '0',
    '-5',
    '1.5',
    'soon',
    'Wed, 21 Oct 2026 07:28:00 GMT',
    '999999',
  ])('ignores %s', (value) => {
    expect(parseRetryAfter(value)).toBeUndefined();
  });
});

describe('skipReason', () => {
  it('has no reason for an analysed row', () => {
    expect(skipReason('analysed')).toBeNull();
  });

  it('describes each skip and falls back for failures', () => {
    expect(skipReason('skipped_low_score')).toMatch(/score gate/);
    expect(skipReason('skipped_cap')).toMatch(/limit/);
    expect(skipReason('skipped_duplicate')).toMatch(/already analysed/);
    expect(skipReason('skipped_failed_recently')).toMatch(/not retried/);
    expect(skipReason('failed')).toMatch(/no usable verdict/);
    expect(skipReason('anything-else')).toMatch(/no usable verdict/);
  });
});
